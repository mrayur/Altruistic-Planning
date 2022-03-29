import numpy as np
with open("D:\sas\IDM_MPC_Vary_init-2022-03-23 15^%02^%50.450370.txt","r", encoding='utf8') as f:
    lines = f.readlines()
    a=[]
    c=[]
    for line in lines:
        if line.startswith('a1'):
            b = list(line)
            b.remove(':')
            b.remove('\n')
            b.remove('\t')
            b.remove('.')
            b.remove(':')
            b.remove(' ')
            b.remove(' ')
            b.remove(' ')
            b.remove('.')
            b=''.join((b))
        if line.startswith('Result'):
            a.append(line)
    for i in a:
        c.append(i.split())
    for i in c:
        i.pop(2)
        i.pop(2)
    e=0
    d=[]
    f=[]
    j=[]
    for i in range(len(c)):
        if c[i][1] == '-1':
            c[i][3] = '10'
    for i in range(int(len(c)/5)):
        e=[float(c[i][1]),float(c[i+1][1]),float(c[i+2][1]),float(c[i+3][1]),float(c[i+4][1])]
        e.count(-1)
        d.append([(float(c[i][3])+float(c[i+1][3])+float(c[i+2][3])+float(c[i+3][3])+float(c[i+4][3]))/5,e.count(-1)])
    for i in d:
        f.append(i[0])
    for i in d:
        j.append(i[1])
    g=np.array(f)
    j=np.array(j)
    h=g.reshape(10,10)
    k=j.reshape(10,10)
    data={'x':h}
    data1={'y':j}
np.savetxt('T.csv',h,delimiter=',')
np.savetxt('ct.csv',k,delimiter=',')