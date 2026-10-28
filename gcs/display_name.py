"""Render only the saved parcel name, cached; never accept host supplied pixels."""
from functools import lru_cache
from pathlib import Path
import subprocess
import sys

@lru_cache(maxsize=128)
def bitmap(name):
    runtime=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    python=str(runtime) if runtime.is_file() else sys.executable
    code="""import sys
from PIL import Image,ImageDraw,ImageFont
text=sys.stdin.buffer.read().decode('utf-8')
font=ImageFont.truetype('C:/Windows/Fonts/NotoSansSC-VF.ttf',18)
while text and font.getlength(text)>190:text=text[:-1]
im=Image.new('1',(192,24));ImageDraw.Draw(im).text((0,-2),text,font=font,fill=1)
sys.stdout.buffer.write(im.tobytes())
"""
    result=subprocess.run([python,'-c',code],input=name.encode('utf-8'),capture_output=True,check=True,timeout=8,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if len(result.stdout)!=576:raise ValueError('Name bitmap size')
    return result.stdout
