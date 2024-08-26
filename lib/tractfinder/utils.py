import sys
import numpy as np
from mrtrix3 import app, ANSI

# Higher than console(), lower than debug()
def info(text):
  if app.VERBOSITY > 1:
    sys.stderr.write(app.EXEC_NAME + ': ' + ANSI.console + text + ANSI.clear + '\n')

## Utility functions for angles and coordinates

# Quick util function for getting angle between two polar points
def ang(azA, polA, azB, polB, dtype=None):
  return np.arccos( np.sin(polA, dtype=dtype)*np.sin(polB, dtype=dtype)*np.cos(azA-azB, dtype=dtype)
                  + np.cos(polA, dtype=dtype)*np.cos(polB, dtype=dtype), dtype=dtype )

def c2s(*args):
    # Arguments supplied as single Nx3 array
    if len(args)==1:
        C = args[0]
        assert C.ndim==2 and C.shape[1]==3
        # r, el, az
        S = np.zeros(C.shape)

        S[:,0] = np.sqrt(np.sum(C**2, axis=1))
    
        S[:,1] = np.arccos(C[:,2]/S[:,0])

        #by chhiara -- start
        #in the case S[:,0]==0, i.e. I am considering the point in the center of the origin od the spherical coordinates,
        #that has has R=0 -> distance ==0 from the center of the origin of the system of spherical coordinates 
        #for example this happens when I am converting the points to deformate P in the spherical coordinates centred in the tumor center.
        #Among the points P there is the center of the tumor and this will have R=0
        #---
        #This cause problems in the computation of the angles S[:,1]  since:
        # C[:,2]/S[:,0] -> creates a number np.inf  (division by zero)
        # np.arccos(np.inf) -> creates a nan  that will create other idiosyncrasies afterward
        #Solution: since the center coordinate point is associated to every angle, let's define a mock angle to subtitute to nan: 0.1
        if (np.isnan(S[:,1])).any():
            print(f" {np.sum(np.isnan(S[:,1]))} nan detected in S[:,1] in utils.c2s function. Let's substitute it with 0.1")
            #check that nan value is only where the R=0
            assert np.where(np.isnan(S[:,1])) == np.where(S[:,0]==0), "I have nan, that are not in correspondance of a Radius=0 (in the center of the spheric coordinates origin)"
            
            S[:,1][np.isnan(S[:,1])]=0.1

        #by chhiara -- end

        S[:,2] = np.arctan2(C[:,1], C[:,0])
        
        return S
    # Arguments supplied individually as 1D X, Y, Z arrays
    elif len(args)==3:
        X, Y, Z = args
        rho = np.sqrt(X**2 + Y**2 + Z**2)
        el = np.arccos(Z / rho)
        az = np.arctan2(Y, X)
        return rho, el, az
    else:
        raise TypeError("Supply either 1 or 3 inputs")

def s2c(*args):
    # Arguments supplied as N*3 array
    if len(args)==1:
        S = args[0]
        assert S.ndim==2

        if S.shape[1]==3:
            # x, y, z
            C = np.zeros(S.shape)

            C[:,0] = S[:,0] * np.sin(S[:,1]) * np.cos(S[:,2])
            C[:,1] = S[:,0] * np.sin(S[:,1]) * np.sin(S[:,2])
            C[:,2] = S[:,0] * np.cos(S[:,1])
            return C
        elif S.shape[1]==2:
            # x, y, z
            C = np.zeros((S.shape[0],3))

            C[:,0] = np.sin(S[:,0]) * np.cos(S[:,1])
            C[:,1] = np.sin(S[:,0]) * np.sin(S[:,1])
            C[:,2] = np.cos(S[:,0])
            return C
        else:
            raise ValueError("Second dimension must have length 2 (if only supplying angles) or 3")
    # Also support only two argumnets (El, Az), assume R=1
    elif len(args)==2:
        El, Az = args
        X = np.sin(El)* np.cos(Az)
        Y = np.sin(El)* np.sin(Az)
        Z = np.cos(El)

        return X, Y, Z
    # 3 Arguments: R, El, Az
    elif len(args)==3:
        R, El, Az = args
        X = R* np.sin(El)* np.cos(Az)
        Y = R* np.sin(El)* np.sin(Az)
        Z = R* np.cos(El)
        return X, Y, Z
