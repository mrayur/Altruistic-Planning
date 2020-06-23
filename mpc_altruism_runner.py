#Optimal Control problem using multiple-shooting
#Multiple-shooting: whole state, trajectory and control trajectory, are decision variables

from casadi import *
import math
import matplotlib.pyplot as plt # for the 'spy' function and plotting results
import numpy as np # to get teh size of matrices
import random # to add noise in mpc
from trajectory_type_definitions import Trajectory

import pdb

def makeIntegrator(dt):
    ##########################################################
    ########## Initialise Variables ##########################

    #2-D state 
    x = MX.sym('x',4) # state <- x,y,v,heading
    u = MX.sym('u',2) # control input <- a,yaw_rate

    ##########################################################
    ########### Define ODE/Dynamics model  ###################

    #computational graph definition of dynamics model
    #Bicycle model
    L = 4 # Length of vehicle #NOTE: this is hardcoded here
    ode = vertcat(x[2]*cos(x[3]+u[1]),x[2]*sin(x[3]+u[1]),u[0],(2*x[2]/L)*sin(u[1]))

    #f is a function that takes as input x and u and outputs the
    # state specified by the ode

    f = Function('f',[x,u],[ode],['x','u'],['ode']) # last 2 arguments name the inputs/outputs (Optional)
    #f([0.2,0.8],0.1) # to see sample output

    ##########################################################
    ########### Implementing the Integrator ##################
    #N = int(T*(1/dt)) # number of control intervals

    #Options for integrator to discretise the system
    # Options are optional
    intg_options = {}
    intg_options['tf'] = dt
    intg_options['simplify'] = True
    intg_options['number_of_finite_elements'] = 4 #number of intermediate steps to integration (?)

    #DAE problem structure/problem definition
    dae = {}
    dae['x'] = x  #What are states    #Define initial trajectories
    dae['p'] = u  # What are parameters (fixed during integration horizon)
    dae['ode'] = f(x,u) # Expression for x_dot = f(x,u)

    # Integrating using Runga-Kutte integration method
    intg = integrator('intg','rk',dae,intg_options) #function object over CasADi symbols

    #Sample output from integrator
    #res = intg(x0=[0,1],p=0) # include object labels to make it easier to identify inputs
    #res['xf'] #print the final value of x at the end of the integration

    #Can call integrator function symbolically
    res = intg(x0=x,p=u) # no numbers give, just CasADi symbols
    x_next = res['xf']

    #This allows us to simplify API
    # Maps straight from inital state x to final state xf, given control input u
    F = Function('F',[x,u],[x_next],['x','u'],['x_next'])

    #Sample output to test simpler API
    #F([0,1],0)
    #F([0.1,.09],0.1)

    return F


def makeOptimiser(dt,horizon,lane_width,speed_limit,accel_range,yaw_rate_range):
    #########################################################
    ##### Make Integrator ###################################
    F = makeIntegrator(dt)

    ##########################################################
    ########### Initialise Optimisation Problem ##############

    N = int(horizon/dt)
    #x_low,x_high,speed_low,speed_high,heading_low,heading_high,accel_low,accel_high,yaw_low,yaw_high
    bounds = [0,2*lane_width,0,speed_limit,0,math.pi,accel_range[0],accel_range[1],\
              yaw_rate_range[0],yaw_rate_range[1]]

    safe_x_radius = 1
    safe_y_radius = 2

    opti = casadi.Opti()

    x = opti.variable(4,N+1) # Decision variables for state trajectory
    u = opti.variable(2,N)
    init_state = opti.parameter(4,1) # Parameter (not optimized over) Initial value for x
    dest_state = opti.parameter(4,1)
    x_other = opti.parameter(4,N+1) # (x,y) position for other vehicle at each timestep
    bnd = opti.parameter(10,1)
    opti.set_value(bnd,bounds)

    safety_params = opti.parameter(2,1)
    opti.set_value(safety_params,[safe_x_radius,safe_y_radius])

    weight = opti.parameter(4,1)
    opti.set_value(weight,[10,0,1,1])

    #opti.minimize(sumsqr((x[:,1:]-dest_state)*weight) + .01*sumsqr(u[1,:])) #Distance to destination
    opti.minimize(sumsqr((x[:,1:]-dest_state)*weight)) # Distance to destination
    #opti.minimize(sumsqr(x-goal) + sumsqr(u)) # Distance to destination
    #opti.minimize(sumsqr(x)+sumsqr(u))

    #This can also be done with functional programming (mapaccum)
    for k in range(N):
        opti.subject_to(x[:,k+1]==F(x[:,k],u[:,k]))
        #safety_constr = sqrt((x[0,k+1]-x_other[0,k+1])**2 + (x[1,k+1]-x_other[1,k+1])**2)
        #opti.subject_to(safety_constr>1)
        safety_constr = ((x[0,k+1]-x_other[0,k+1])/safety_params[0])**2 + ((x[1,k+1]-x_other[1,k+1])/safety_params[1])**2
        opti.subject_to(safety_constr>1)

    #X-coord constraints
    opti.subject_to(bnd[0]<=x[0,:])
    opti.subject_to(x[0,:]<=bnd[1])
    #Velocity Contraints
    opti.subject_to(bnd[2]<=x[2,:])
    opti.subject_to(x[2,:]<=bnd[3])
    #Heading Constraints
    opti.subject_to(bnd[4]<=x[3,:])
    opti.subject_to(x[3,:]<=bnd[5])
    #Accel Constraints
    opti.subject_to(bnd[6]<=u[0,:])
    opti.subject_to(u[0,:]<=bnd[7])
    #Yaw Rate Constraints
    opti.subject_to(bnd[8]<=u[1,:])
    opti.subject_to(u[1,:]<=bnd[9])
    #Initial position contraints
    opti.subject_to(x[:,0]==init_state) #Initial state

    ###########################################################
    ########### Define Optimizer ##############################

    ipopt_opts = {}
    #Stop IPOPT printing output
    ipopt_opts["ipopt.print_level"] = 0;
    ipopt_opts["ipopt.sb"] = "yes";
    ipopt_opts["print_time"] = 0
    #Cap the maximum number of iterations
    ipopt_opts["ipopt.max_iter"] = 500

    opti.solver('ipopt',ipopt_opts)

    #Turn optimisation to CasADi function
    M = opti.to_function('M',[init_state,dest_state,x_other],[x[:,1:],u[:,1:]],\
                           ['init','dest','x_other'],['x_opt','u_opt'])

    #M contains SQP method, which maps to a QP solver, all contained in a single, differentiable,
    #computational graph

    return M


#####################################################################################################
#####################################################################################################
#Trajectory Stuff

def makeTrajectories(cur_state,spec,T,init_state=None):
    """Returns a list of trajectories starting from cur_state, of length T.
       Spec is a list of (dx,dv) pairs, where each pair corresponds to a distinct trajectory
       specification.
       If init_state is specified then the destination states for the trajectories will be set
       from init_state (as opposed to cur state)"""
    traj_list = []

    # Init_state is the state the trajectories are supposed to have originated at. If init_state is None then
    # assume the current state is the initial state of the trajectory
    if init_state is None:
        init_state = cur_state

    #pdb.set_trace()

    for dx,dv in zip([x[0] for x in spec], [x[1] for x in spec]):
        label = "dx-{},dv-{}".format(dx,dv)
        dest_state = dict(init_state)
        dest_state["position"] = tuple([dest_state["position"][0]+dx,dest_state["position"][1]])
        dest_state["velocity"] += dv
        dest_state["parametrised_acceleration"] = (0,0) #parametrised acceleration is introduced to handle acceleration constraints
        traj = Trajectory(cur_state,dest_state,T,label)
        traj_list.append(traj)

    return traj_list


def getParametrisedAcceleration(vel,heading,accel,yaw_rate,axle_length):
    x_dot = vel*math.cos(math.radians(heading))
    y_dot = vel*math.sin(math.radians(heading))
    x_dot_dot = (vel*accel/x_dot) - (y_dot/x_dot)*(1/vel)*(y_dot*accel - (x_dot*(vel**2)*math.tan(math.radians(yaw_rate))/axle_length))
    y_dot_dot = (1/vel)*(y_dot*accel - (x_dot*(vel**2)*math.tan(math.radians(yaw_rate))/axle_length))

    return (x_dot_dot,y_dot_dot)


def filterState(state,axle_length):
    state = dict(state)
    state["heading"] = math.degrees(state["heading"])
    state["parametrised_acceleration"] = getParametrisedAcceleration(state["velocity"],state["heading"],state["acceleration"],state["yaw_rate"],axle_length)

    return state

def makeTrajState(pos_x,pos_y,v,heading,accel,yaw_rate,axle_length):
    return filterState({"position":(pos_x,pos_y),"velocity":v,"heading":heading,"acceleration": accel, "yaw_rate": yaw_rate},axle_length)


###################################################################################################
####### Reward Grid Stuff #########################################################################

def makeBaselineRewardGrid(reward_grid):
    return reward_grid


def makeVanillaAltRewardGrid(reward_grid,alt1,alt2):
    alt_reward = np.copy(reward_grid)
    alt_reward[:,:,0] = (1-alt1)*reward_grid[:,:,0] + alt1*reward_grid[:,:,1]
    alt_reward[:,:,1] = (1-alt2)*reward_grid[:,:,1] + alt2*reward_grid[:,:,0]

    return alt_reward


def makeAugmentedAltRewardGrid(reward_grid,alt1,alt2):
    alt_reward = np.copy(reward_grid)
    alt_reward[:,:,0] = ((1-alt1)*reward_grid[:,:,0] + alt1*(1-alt2)*reward_grid[:,:,1])/(1-alt1*alt2)
    alt_reward[:,:,1] = ((1-alt2)*reward_grid[:,:,1] + alt2*(1-alt1)*reward_grid[:,:,0])/(1-alt1*alt2)

    return alt_reward


def makeSVORewardGrid(reward_grid,svo1,svo2):
    alt_reward = np.copy(reward_grid)
    alt_reward[:,:,0] = math.cos(svo1)*reward_grid[:,:,0] + math.sin(svo1)*reward_grid[:,:,1]
    alt_reward[:,:,1] = math.cos(svo2)*reward_grid[:,:,1] + math.sin(svo2)*reward_grid[:,:,0]

    return alt_reward

        

###################################################################################################

def computeDistance(x1,x2):
    #distance from desired x-position and velocity
    return math.sqrt((x1[0]-x2[0])**2 + (x1[2]-x2[2])**2)

if __name__ == "__main__":
    ###################################
    #Number of times to run experiments
    num_its = 100

    ###################################
    ###################################
    #Optimiser Parameters
    axle_length = 4
    dt = .2
    epsilon = .5
    lane_width = 5
    T = 10 #Trajectory length
    lookahead_horizon = 4 # length of time MPC plans over
    N = int(lookahead_horizon/dt)

    speed_limit = 15
    accel_range = [-3,3]
    yaw_rate_range = [-math.pi/18,math.pi/18]    

    init_c1_posit = [0.5*lane_width,0] # middle of right lane
    init_c2_posit = [1.5*lane_width,0] # middle of right lane
    init_c1_vel = 10
    init_c2_vel = 10
    init_c1_heading = math.pi/2
    init_c2_heading = math.pi/2
    init_c1_accel = 0
    init_c2_accel = 0
    init_c1_yaw_rate = 0
    init_c2_yaw_rate = 0

    c1_init_state = makeTrajState(init_c1_posit[0],init_c1_posit[1],init_c1_vel,\
                                  init_c1_heading,init_c1_accel,init_c1_yaw_rate,axle_length)
    c2_init_state = makeTrajState(init_c2_posit[0],init_c2_posit[1],init_c2_vel,\
                                  init_c2_heading,init_c2_accel,init_c2_yaw_rate,axle_length)
    ###################################
    ##Define Trajectory Options
    c1_traj_specs = [(0,0),(lane_width,0)]
    c2_traj_specs = [(0,0),(0,-10)]

    optimiser = makeOptimiser(dt,lookahead_horizon,lane_width,speed_limit,accel_range,yaw_rate_range)

    #alt_values = [.2*x for x in range(6)]

    #Use float values or else numpy will round to int
    #reward_grid = np.array([[[-np.inf,-np.inf],[0,1]],[[1,0],[-np.inf,-np.inf]]])
    reward_grid = np.array([[[-1.0,-1.0],[0.0,1.0]],[[1.0,0.0],[-1.0,-1.0]]])


    a1 = .48
    a2 = .48

    #alt_values = [0,.25,.5,.75,.99]
    #for a1 in alt_values:
    #    for a2 in alt_values:
    #np.random.seed(0)
    #for _ in range(num_its)
    #goal_grid = makeBaselineRewardGrid(reward_grid,a1,a2)
    goal_grid = makeVanillaAltRewardGrid(reward_grid,a1,a2)
    #goal_grid = makeAugmentedAltRewardGrid(reward_grid,a1,a2)
    #goal_grid = makeSVORewardGrid(reward_grid,a1,a2)
    #goal_grid = makeRecipriocalRewardGrid(reward_grid,a1,a2)
    
    
    c1_index = np.unravel_index(np.argmax(goal_grid[:,:,0]),goal_grid[:,:,0].shape)[0]
    c1_c2_index = np.unravel_index(np.argmax(goal_grid[c1_index,:,1]),\
                          goal_grid[c1_index,:,1].shape)[0] #c2's optimal choice if c1 is lead
    c2_index = np.unravel_index(np.argmax(goal_grid[:,:,1]),goal_grid[:,:,1].shape)[1]
    c2_c1_index = np.unravel_index(np.argmax(goal_grid[:,c2_index,0]),\
                          goal_grid[:,c2_index,0].shape)[0] # c1 optimal choice of c2 lead

    c1_x = np.array([*init_c1_posit,init_c1_vel,init_c1_heading]).reshape(4,1)
    c2_x = np.array([*init_c2_posit,init_c2_vel,init_c2_heading]).reshape(4,1)

    c1_u = np.array([0,0]).reshape(2,1)
    c2_u = np.array([0,0]).reshape(2,1)

    c1_dest = np.copy(c1_x)
    c1_dest[0] += c1_traj_specs[c1_index][0]
    c1_dest[2] += c1_traj_specs[c1_index][1]
    
    c2_dest = np.copy(c2_x)
    c2_dest[0] += c2_traj_specs[c2_index][0]
    c2_dest[2] += c2_traj_specs[c2_index][1]

    t = 0
    c1_t,c2_t = None,None
    c1_mpc_x,c2_mpc_x = np.array(c1_x),np.array(c2_x)
    c1_mpc_u,c2_mpc_u = np.array(c1_u),np.array(c2_u)
    num_timesteps = 4
    #while t<T and (computeDistance(c1_x,c1_dest)>epsilon or computeDistance(c2_x,c2_dest)>epsilon):
    while t<T and (c1_t is None or c2_t is None):
        ################################
        #### MPC for C1 ################
        c1_c2_traj = makeTrajectories(makeTrajState(*[x[0] for x in c2_x.tolist()],*[x[0] for x in c2_u.tolist()],axle_length),\
                                      [c2_traj_specs[c1_c2_index]],T-t,c2_init_state)[0]
        c1_c2_posit = c1_c2_traj.completePositionList(dt)
        c1_c2_vel = c1_c2_traj.completeVelocityList(dt)
        c1_c2_heading = [math.radians(x) for x in c1_c2_traj.completeHeadingList(dt)]
        # Not enough trajectory left, assume constant velocity thereafter
        if len(c1_c2_posit)<N+1:
            c1_c2_backup_traj = makeTrajectories(c1_c2_traj.state(T,axle_length),[(0,0)],T)[0]
            c1_c2_posit += c1_c2_backup_traj.completePositionList(dt)
            c1_c2_vel += c1_c2_backup_traj.completeVelocityList(dt)
            c1_c2_heading += [math.radians(x) for x in c1_c2_backup_traj.completeHeadingList(dt)]

        c1_c2_posit = c1_c2_posit[:N+1]
        c1_c2_vel = c1_c2_vel[:N+1]
        c1_c2_heading = c1_c2_heading[:N+1]

        c1_c2_x = np.array([[x[0] for x in c1_c2_posit],[x[1] for x in c1_c2_posit],\
                            c1_c2_vel,c1_c2_heading])
        c1_opt_x,c1_opt_u = optimiser(c1_x,c1_dest,c1_c2_x)

        ################################
        #### MPC for C2 ################
        c2_c1_traj = makeTrajectories(makeTrajState(*[x[0] for x in c1_x.tolist()],*[x[0] for x in c1_u.tolist()],axle_length),\
                                      [c1_traj_specs[c2_c1_index]],T-t,c1_init_state)[0]
        c2_c1_posit = c2_c1_traj.completePositionList(dt)
        c2_c1_vel = c2_c1_traj.completeVelocityList(dt)
        c2_c1_heading = [math.radians(x) for x in c2_c1_traj.completeHeadingList(dt)]
        # Not enough trajectory left, assume constant velocity thereafter
        if len(c2_c1_posit)<N+1:
            c2_c1_backup_traj = makeTrajectories(c2_c1_traj.state(T,axle_length),[(0,0)],T)[0]
            c2_c1_posit += c2_c1_backup_traj.completePositionList(dt)
            c2_c1_vel += c2_c1_backup_traj.completeVelocityList(dt)
            c2_c1_heading += [math.radians(x) for x in c2_c1_backup_traj.completeHeadingList(dt)]

        c2_c1_posit = c2_c1_posit[:N+1]
        c2_c1_vel = c2_c1_vel[:N+1]
        c2_c1_heading = c2_c1_heading[:N+1]
        c2_c1_x = np.array([[x[0] for x in c2_c1_posit],[x[1] for x in c2_c1_posit],\
                            c2_c1_vel,c2_c1_heading])
        c2_opt_x,c2_opt_u = optimiser(c2_x,c2_dest,c2_c1_x)
        
        #if np.max(c1_opt_x[0,:])<2 or np.max(c1_opt_x[0,:])>3 or np.max(c2_opt_x[0,:])<7 or np.max(c2_opt_x[0,:])>8:
        #    print("Problem here")
        #    pdb.set_trace()

        c1_x = np.array(c1_opt_x[:,num_timesteps-1])
        c2_x = np.array(c2_opt_x[:,num_timesteps-1])
        c1_u = np.array(c1_opt_u[:,num_timesteps-1])
        c2_u = np.array(c2_opt_u[:,num_timesteps-1])
        t += num_timesteps*dt

        c1_mpc_x = np.hstack((c1_mpc_x,np.array(c1_opt_x[:,:num_timesteps])))
        c2_mpc_x = np.hstack((c2_mpc_x,np.array(c2_opt_x[:,:num_timesteps])))
        c1_mpc_u = np.hstack((c1_mpc_u,np.array(c1_opt_u[:,:num_timesteps])))
        c2_mpc_u = np.hstack((c2_mpc_u,np.array(c2_opt_u[:,:num_timesteps])))


        if c1_t is None and computeDistance(c1_x,c1_dest)<epsilon: c1_t = t
        if c2_t is None and computeDistance(c2_x,c2_dest)<epsilon: c2_t = t

        print("T is: {}\tD1: {}\t D2: {}".format(t,computeDistance(c1_x,c1_dest),computeDistance(c2_x,c2_dest)))

        # simulate system
        #x = F(x,u).full() + np.array([0,random.random()*.02]).reshape(2,1) # adding some noise
        #x = F(x,u).full()

    #print("MPC Complete")
    #t2 = datetime.datetime.now()
    #print("Time: {}".format(t2-t1))
    #pdb.set_trace()

    ########################################################################
    #### Plot Resulting Trajectories
    #import matplotlib.pyplot as plt
    #import time

    #c1_plt_x = []
    #c1_plt_y = []
    #c2_plt_x = []
    #c2_plt_y = []

    #y_lim = max(np.max(c1_mpc_x[1,:]),np.max(c2_mpc_x[1,:]))*1.1

    #plt.ion()
    #plt.figure()
    #plt.xlim(0,2*lane_width)
    #plt.ylim(0,y_lim)

    #for i in range(c1_mpc_x.shape[1]):
    #    c1_plt_x.append(c1_mpc_x[0,i])
    #    c1_plt_y.append(c1_mpc_x[1,i])
    #    c2_plt_x.append(c2_mpc_x[0,i])
    #    c2_plt_y.append(c2_mpc_x[1,i])
    #    plt.plot(c1_plt_x,c1_plt_y,'g-')
    #    plt.plot(c2_plt_x,c2_plt_y,'r-')
    #    plt.draw()
    #    plt.pause(1e-17)
    #    time.sleep(dt)

    #pdb.set_trace()

#####################################
