import os
import array
import random
import math
import csv
import argparse
import time
import itertools
import operator
import numpy
import joblib
import subprocess

# from joblib import Parallel, delayed, parallel_backend
# from distributed.joblib import DaskDistributedBackend
from threading import Timer

from deap import algorithms
from deap import base
from deap import creator
from deap import tools

from GA import customMap
from GA import networks
from GA import phenome
from GA import networkedgeneticalgorithm as nga
from GA import grayencoder as ge

from Sims import lammpsbuilder as lb

from Tools import misctools
from Tools import listtools

from nanoparticle import NanoParticlePhenome
from membranesimulation import MembraneSimulation

parser = argparse.ArgumentParser(description='')
parser.add_argument('-n','--ngen', default=50,type=int,
                    help='number of generations')
parser.add_argument('-f','--freq', default=2, type=int,
                    help='number of generations between migrations')
parser.add_argument('-d','--demes', default=10, type=int,
                    help='number of demes to run over')
parser.add_argument('-p','--pop', default=10, type=int,
                    help='population of each deme')
parser.add_argument('-gs','--genomesize', default=100, type=int,
                    help='number of bits in the genome')
parser.add_argument('-c','--cxpb', default=0.5,  type=float,
                    help='independant probability of crossover')
parser.add_argument('-m','--mutpb', default=0.2, type=float,
                    help='independant probability of mutation')
parser.add_argument('-mg','--migrations', default=1, type=int,
                    help='number of migrations to do each time')
parser.add_argument('-mpb','--mindpb', default=0.05, type=float,
                    help='independant probability of a bit flip')
parser.add_argument('-t','--tournsize', default=3, type=int,
                    help='size of selection tournaments')
parser.add_argument('-v','--verbose', default=False, action='store_true',
                    help='option to run in verbose mode')
parser.add_argument('-g','--graph', default='islands', 
                    choices=['singlet','islands','star','megastar'],
                    help='type of network to use')
parser.add_argument('-s','--seed', default=int(time.time()), type=int,
                    help='seed for the RNG')
parser.add_argument('-hof','--hofsize', default=5, type=int,
                    help='hall of fame size')


args = parser.parse_args()
wd = os.path.dirname(os.path.realpath(__file__))

NSPOKES = 2
NISLES = args.demes
ISLESIZE = args.pop
CXPB=args.cxpb
MUTPB=args.mutpb
NGEN, FREQ = args.ngen, args.freq
VERBOSE=args.verbose
SEED = args.seed
TSIZE = args.tournsize
MINPDB = args.mindpb
GENOMESIZE = args.genomesize
MIGR = args.migrations
HOFSIZE = args.hofsize


def kill(p):
    try:
        print "killing "+str(p) 
        p.kill()
    except OSError:
        pass # ignore

def exit(signal, frame):
        os._exit(1)

def saveMetrics(lis,filename='out.csv'):
    with open(filename,'wb') as out:
        csv_out=csv.DictWriter(out,lis[-1].keys())
        csv_out.writeheader()
        for row in lis:
            csv_out.writerow(row)

def evaluateNPWrapping(outFilename,runtime):
    minFit = 1E-8
    outData = []
    if(not os.path.exists(outFilename)):
            #print "no outfile"
            return minFit,

    with open(outFilename, 'r+') as f:
        lines = f.readlines()
        for i in range(len(lines)):
            if str(runtime) in lines[i]:
                lines[i] = ""
                break
            lines[i] = ""

        for line in lines:
            if line != "":
                outData.append(line.replace("\n","").replace(" ",","))


    os.remove(outFilename)

    if len(outData)<50:
        #print str(outData)
        return minFit,



    outVectors = {}
    for line in outData:
        slist = line.split(",")
        if(len(slist)<3):
            return minFit,
        if int(slist[0]) in outVectors:
            outVectors[int(slist[0])].append({'x':float(slist[1]),'y':float(slist[2])})
        else:
            outVectors[int(slist[0])] = []
            outVectors[int(slist[0])].append({'x':float(slist[1]),'y':float(slist[2])})

    magnitudes = []
    boxsize = 20
    for key, value in outVectors.iteritems():
        if key == 3:
            for v in value:
                inrange = 0
                fmag = 0
                for v2 in outVectors[1]:
                    xd = v['x']-v2['x']
                    yd = v['y']-v2['y']
                    m = math.sqrt(xd*xd+yd*yd)
                    if(m<7.0):
                        inrange+=1
                if(inrange>0):
                    magnitudes.append(inrange)

    if len(magnitudes)<1:
        #print str(num) + " protein out of range"
        return minFit,

    msum = 0
    for m in magnitudes:
        msum += m

    if(msum == 0):
        #print "no msum"
        return minFit,

    return msum,

def runCmd(cmd,timeout):
    try:
        with open('log.log', 'w+') as f:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdout=f, 
                stderr=f
                )
            t = Timer(45, kill, [proc])
            t.start()
            proc.wait()
            t.cancel()
    except Exception as e: 
        print cmd
        print e

def makeXYPair(individual,xMax,xMin,yMax,yMin):
    halfs = listtools.subdivide(individual,int(len(individual)*0.5))
    a = ge.read(halfs[0])
    b = ge.read(halfs[1])
    maxA = ge.max(halfs[0])
    maxB = ge.max(halfs[1])
    xRange = xMax -xMin
    yRange = yMax -yMin
    x=float((a/float(maxA))*xRange + xMin)
    y=float((b/float(maxB))*yRange +yMin)
    return x,y

def performanceTest(individual):
    x,y = makeXYPair(individual,2,-2,2,-2)
    f1 = (x + y + 1)
    f2 = (2*x - 3*y)
    f = -(1 + (f1*f1)*(19 - 14*x + 3*x*x - 14*y + 6*x*y + 3*y*y))*(30 + (f2*f2)*(18 - 32*x + 12*x*x + 48*y - 36*x*y + 27*y*y))
    return f,

def evaluate(individual):
    phenome = NanoParticlePhenome(individual,8,8,0,10)
    np = phenome.particle
    sim = MembraneSimulation(
        'sim_'+misctools.randomStr(10),
        np,
        250000,
        0.01,
        '../out/',
        'run/',
        wd+'/Data/relaxed-membrane.xyz'
        )
    sim.saveFiles()
    path = (wd+"/"+sim.filedir).replace(' ','\ ')
    cmd = "cd "+ path + " && lammps -in "+sim.scriptName+" > lammps.out"
    runCmd(cmd,45)
    time.sleep(0.1)
    outpath = wd+"/out/"
    outFile = outpath+sim.name+"_out.xyz"
    f = 1E-8,
    f = evaluateNPWrapping(outFile,250000)
    sim.deleteFiles()
    #os.remove(outFile.replace('\ ',' '))
    return f

def sel(pop,k):
    return tools.selTournament(pop,k,TSIZE)

def mut(individual):
    return tools.mutFlipBit(individual,MINPDB)

def algorithm(pop,toolbox,stats,hof):
    return algorithms.eaSimple(pop,toolbox=toolbox,
        cxpb=CXPB, mutpb=MUTPB, ngen=FREQ,verbose=VERBOSE,stats=stats,halloffame=hof)

def beforeMigration(ga):
    saveHOF(ga.hof,ga.gen)
    return

def afterMigration(ga):
    outFile = ""
    isleNum = 0
    i = 0
    for isle in ga.islands:
        isleNum += 1
        points = [makeXYPair(p,2,-2,2,-2) for p in isle]
        fit = [p.fitness.values[-1] for p in isle]
        for p in points:
            i+=1
            outFile += str(i)+","+str(p[0])+","+str(p[1])+"\n"
    with open("coords.csv", 'a') as file_:
        file_.write(outFile)
    return

def saveHOF(hof,code):
    i = 0
    for ind in hof:
        i+=1
        phenome = NanoParticlePhenome(ind,8,8,0,10)
        np = phenome.particle
        sim = MembraneSimulation(
            'hof_'+str(code)+'_'+str(i),
            np,
            250000,
            0.01,
            '../out/',
            'hof/',
            wd+'/Data/relaxed-membrane.xyz'
            )
        sim.saveFiles()

def main():

    if args.graph == 'singlet':
        network = networks.createSinglets(NISLES)
    elif args.graph == 'islands':
        network = networks.createIslands(NISLES)
    elif args.graph == 'star':
        network = networks.createStar(NISLES-1)
    elif args.graph == 'megastar':
        network = networks.createMegaStar(NSPOKES,int(math.ceil((NISLES-3)*0.25)),int(math.floor((NISLES-3)*0.25)))
    else:
        raw_input('malformed network option, continue with islands? (Enter)')

    random.seed(args.seed)
    ga = nga.NetworkedGeneticAlgorithm(
        genomeSize = GENOMESIZE,
        islePop = ISLESIZE,
        hofSize = HOFSIZE,
        evaluate = evaluate,
        sel = sel,
        net = network,
        subroutine = algorithm,
        mut = mut,
        beforeMigration = beforeMigration,
        afterMigration = afterMigration,
        verbose = VERBOSE)

    results = ga.run(NGEN,FREQ,MIGR)

    
    #print(results[0][0][0])
    saveMetrics(results[-1])

    saveHOF(results[1],str(NGEN))


if __name__ == "__main__":
    main()