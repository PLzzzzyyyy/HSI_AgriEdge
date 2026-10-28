"""Display-only messages on the existing UDP owner; no task/inference commands."""
import math
import struct
import zlib

PARCEL=0x15
MIRROR=0x16
TEMP=0x89
FRAME=0x8a

def parcel_body(job,revision,parcel,row,threshold,name_bits,serial):
    a=job.audit
    points=[] if parcel is None else parcel['pts']
    if len(name_bits)!=576 or not 0<=threshold<=1 or not 0<serial<2**32:raise ValueError('Display payload')
    counts=[0]*24 if row is None else row['class_counts']+[0]*(24-len(row['class_counts']))
    n=0 if row is None else row['pixels'];received=0 if row is None else row['received_pixels']
    low=0 if row is None else row['low_pixels']
    body=struct.pack('<9IH6B24I',a.boot,a.session,a.crc,revision,0 if parcel is None else zlib.crc32(parcel['id'].encode()),serial,n,received,low,
                     round(threshold*65535),a.scene_id,len(a.identity['classes']) if isinstance(a.identity.get('classes'),list) else a.identity['classes'],len(points),int(parcel is not None),0,0,*counts)
    body+=b''.join(struct.pack('<HH',round(x/a.scene_width*65535),round(y/a.scene_height*65535)) for x,y in points)
    return body+name_bits

def temperature(data,boot,session):
    if len(data)!=40 or struct.unpack_from('<HBB',data)!=(0x4548,TEMP,1):raise ValueError('Temperature header')
    b,s,counter,age,current,peak,valid=struct.unpack_from('<IIIIffI',data,12)
    if (b,s)!=(boot,session) or valid>1:raise ValueError('Temperature identity')
    if valid and (not math.isfinite(current) or not math.isfinite(peak) or not -40<=current<=peak<=125):raise ValueError('Temperature range')
    return dict(temp_c=current if valid else None,temp_peak_c=peak if valid else None,valid=bool(valid),sample_counter=counter,sample_age_ms=age,source='PS_SYSMON_DIE',boot_id=f'{b:08x}')

def frame_chunk(data,boot,session,request):
    if len(data)<40 or struct.unpack_from('<HBB',data)!=(0x4548,FRAME,1):raise ValueError('Mirror header')
    b,s,r,total,offset,crc,w,h=struct.unpack_from('<IIIIIIHH',data,12)
    if (b,s,r)!=(boot,session,request) or (w,h)!=(1920,1080) or not 0<total<=1920*1080*4 or offset+len(data)-40>total:raise ValueError('Mirror identity/size')
    return total,offset,crc,data[40:]

def png_from_rle(raw,width=1920,height=1080):
    if len(raw)%4:raise ValueError('Mirror RLE alignment')
    image=bytearray()
    for n,pixel in struct.iter_unpack('<HH',raw):
        if not n or len(image)//3+n>width*height:raise ValueError('Mirror RLE count')
        rgb=bytes((((pixel>>11)&31)*255//31,((pixel>>5)&63)*255//63,(pixel&31)*255//31))
        image.extend(rgb*n)
    if len(image)!=width*height*3:raise ValueError('Mirror incomplete pixels')
    filtered=b''.join(b'\0'+image[y*width*3:(y+1)*width*3] for y in range(height))
    def chunk(kind,payload):return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(filtered,3))+chunk(b'IEND',b'')
