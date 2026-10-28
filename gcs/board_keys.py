"""Physical key transport and geometry. No inference or ground-truth access."""
import math
import random
import struct

EVENT=0x8b
RECEIPT=0x17
SCENES=('longkou','honghu','hanchuan')
GSD_MM=(463,43,109)

def decode(data,boot,session):
    if len(data)!=28 or struct.unpack_from('<HBB',data)!=(0x4548,EVENT,1):raise ValueError('Key event header')
    b,s,serial,key,gesture,scene,reserved=struct.unpack_from('<IIIBBBB',data,12)
    if (b,s)!=(boot,session) or not serial or key not in (5,6) or gesture not in (1,2,3) or scene>2 or reserved:
        raise ValueError('Key event identity/range')
    return dict(boot_id=b,session=s,id=serial,key=key,gesture=gesture,scene=SCENES[scene],requested_scene=SCENES[scene])

def receipt(boot,session,serial,state,code,scene):
    if state not in (2,3,4) or not 0<=code<=255:raise ValueError('Key receipt')
    return struct.pack('<IIIBBBB',boot,session,serial,state,code,SCENES.index(scene),0)

def rectangle(scene,height,width,rng=None,max_pixels=4096):
    rng=rng or random.SystemRandom()
    mm=GSD_MM[SCENES.index(scene)]
    cap=min(height*width,6000*1000000//(mm*mm),max_pixels)
    if height<1 or width<1 or cap<1:raise ValueError('Empty key ROI')
    # Separate physical-area and pixel budgets: small-GSD scenes must not
    # accidentally turn a demo rectangle into hundreds of thousands of pixels.
    lo=min(16,width,cap)
    w=rng.randint(lo,min(width,cap,max(16,math.isqrt(cap)*2)))
    h=rng.randint(min(16,height,cap//w),min(height,cap//w))
    return [rng.randrange(height-h+1),rng.randrange(width-w+1),h,w]

def polygon(scene,height,width,rng=None,max_pixels=4096):
    rng=rng or random.SystemRandom()
    if min(height,width)<8:raise ValueError('Scene too small for parcel')
    r,c,h,w=rectangle(scene,height,width,rng,max_pixels)
    if min(h,w)<4:raise ValueError('Pixel budget too small for parcel')
    n=rng.randint(3,5);rotation=rng.random()*2*math.pi
    # Points on an ellipse in increasing angular order form a simple convex
    # polygon; retain floating boundaries to avoid rounding collisions.
    pts=[]
    for i in range(n):
        angle=rotation+2*math.pi*(i+rng.uniform(-.12,.12))/n
        pts.append([c+w/2+(w/2-.5)*math.cos(angle),r+h/2+(h/2-.5)*math.sin(angle)])
    x0=math.floor(min(p[0] for p in pts));y0=math.floor(min(p[1] for p in pts))
    x1=math.ceil(max(p[0] for p in pts));y1=math.ceil(max(p[1] for p in pts))
    return [y0,x0,y1-y0,x1-x0],pts
