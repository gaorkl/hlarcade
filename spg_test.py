import numpy as np
from array import array

# from minigl.hlcontext import HLContext
# from minigl.hlbuffer import HLBuffer

# ctx = HLContext()
# buffer = ctx.buffer(data=array('f', (0,1,2,3)))

from gl_custom.context import Context
ctx = Context()
buffer = ctx.buffer(data=array('f', (0,1,4,3)))

print(np.frombuffer(buffer.read(), dtype=np.float32))

fbo = ctx.framebuffer(
    color_attachments=[
        ctx.texture( (100, 100), components=4 )
    ]
)

with fbo.activate() as fbo:
    fbo.clear( (0,123,124) )

print(np.frombuffer(fbo.read(), dtype=np.uint8).reshape(100, 100, 3))


from arcade.sprite import Sprite
image_source = ":resources:images/animated_characters/female_adventurer/femaleAdventurer_idle.png"
player_sprite = Sprite(image_source)
player_sprite.set_position(10, 10)


