from contextlib import contextmanager
from ctypes import c_int, c_char_p, cast, c_float
from collections import deque
import logging
from typing import Any, Deque, Dict, List, Tuple, Union, Sequence, Set

import pyglet
pyglet.options["headless"] = True

from pyglet import gl

from typing import Optional

# from hlbuffer import HLBuffer, HLTexture, HLFramebuffer

from .hlbuffer import HLBuffer
# from .hltexture import HLTexture
# from .hlframebuffer import HLFramebuffer

LOG = logging.getLogger(__name__)


class HLContext:
    """
    Represents an OpenGL context. This context belongs to a ``pyglet.Window``
    normally accessed through ``window.ctx``.
    The Context class contains methods for creating resources,
    global states and commonly used enums. All enums also exist
    in the ``gl`` module. (``ctx.BLEND`` or ``arcade.gl.BLEND``).
    """

    #: The active context
    active: Optional["HLContext"] = None

    # --- Store the most commonly used OpenGL constants
    # Texture
    #: Texture interpolation: Nearest pixel
    NEAREST = 0x2600
    #: Texture interpolation: Linear interpolate
    LINEAR = 0x2601
    #: Texture interpolation: Minification filter for mipmaps
    NEAREST_MIPMAP_NEAREST = 0x2700
    #: Texture interpolation: Minification filter for mipmaps
    LINEAR_MIPMAP_NEAREST = 0x2701
    #: Texture interpolation: Minification filter for mipmaps
    NEAREST_MIPMAP_LINEAR = 0x2702
    #: Texture interpolation: Minification filter for mipmaps
    LINEAR_MIPMAP_LINEAR = 0x2703

    #: Texture wrap mode: Repeat
    REPEAT = gl.GL_REPEAT
    # Texture wrap mode: Clamp to border pixel
    CLAMP_TO_EDGE = gl.GL_CLAMP_TO_EDGE
    # Texture wrap mode: Clamp to border color
    CLAMP_TO_BORDER = gl.GL_CLAMP_TO_BORDER
    # Texture wrap mode: Repeat mirrored
    MIRRORED_REPEAT = gl.GL_MIRRORED_REPEAT

    # Flags
    #: Context flag: Blending
    BLEND = gl.GL_BLEND
    #: Context flag: Depth testing
    DEPTH_TEST = gl.GL_DEPTH_TEST
    #: Context flag: Face culling
    CULL_FACE = gl.GL_CULL_FACE
    #: Context flag: Enable ``gl_PointSize`` in shaders.
    PROGRAM_POINT_SIZE = gl.GL_PROGRAM_POINT_SIZE

    # Blend functions
    #: Blend function
    ZERO = 0x0000
    #: Blend function
    ONE = 0x0001
    #: Blend function
    SRC_COLOR = 0x0300
    #: Blend function
    ONE_MINUS_SRC_COLOR = 0x0301
    #: Blend function
    SRC_ALPHA = 0x0302
    #: Blend function
    ONE_MINUS_SRC_ALPHA = 0x0303
    #: Blend function
    DST_ALPHA = 0x0304
    #: Blend function
    ONE_MINUS_DST_ALPHA = 0x0305
    #: Blend function
    DST_COLOR = 0x0306
    #: Blend function
    ONE_MINUS_DST_COLOR = 0x0307

    # Blend equations
    #: source + destination
    FUNC_ADD = 0x8006
    #: Blend equations: source - destination
    FUNC_SUBTRACT = 0x800A
    #: Blend equations: destination - source
    FUNC_REVERSE_SUBTRACT = 0x800B
    #: Blend equations: Minimum of source and destination
    MIN = 0x8007
    #: Blend equations: Maximum of source and destination
    MAX = 0x8008

    # Blend mode shortcuts
    #: Blend mode shortcut for default blend mode: ``SRC_ALPHA, ONE_MINUS_SRC_ALPHA``
    BLEND_DEFAULT = 0x0302, 0x0303
    #: Blend mode shortcut for additive blending: ``ONE, ONE``
    BLEND_ADDITIVE = 0x0001, 0x0001
    #: Blend mode shortcut for premultipled alpha: ``SRC_ALPHA, ONE``
    BLEND_PREMULTIPLIED_ALPHA = 0x0302, 0x0001

    # VertexArray: Primitives
    #: Primitive mode
    POINTS = gl.GL_POINTS  # 0
    #: Primitive mode
    LINES = gl.GL_LINES  # 1
    #: Primitive mode
    LINE_LOOP = gl.GL_LINE_LOOP  # 2
    #: Primitive mode
    LINE_STRIP = gl.GL_LINE_STRIP  # 3
    #: Primitive mode
    TRIANGLES = gl.GL_TRIANGLES  # 4
    #: Primitive mode
    TRIANGLE_STRIP = gl.GL_TRIANGLE_STRIP  # 5
    #: Primitive mode
    TRIANGLE_FAN = gl.GL_TRIANGLE_FAN  # 6
    #: Primitive mode
    LINES_ADJACENCY = gl.GL_LINES_ADJACENCY  # 10
    #: Primitive mod
    LINE_STRIP_ADJACENCY = gl.GL_LINE_STRIP_ADJACENCY  # 11
    #: Primitive mode
    TRIANGLES_ADJACENCY = gl.GL_TRIANGLES_ADJACENCY  # 12
    #: Primitive mode
    TRIANGLE_STRIP_ADJACENCY = gl.GL_TRIANGLE_STRIP_ADJACENCY  # 13
    #: Patch mode (tessellation)
    PATCHES = gl.GL_PATCHES

    # The most common error enums
    _errors = {
        gl.GL_INVALID_ENUM: "GL_INVALID_ENUM",
        gl.GL_INVALID_VALUE: "GL_INVALID_VALUE",
        gl.GL_INVALID_OPERATION: "GL_INVALID_OPERATION",
        gl.GL_INVALID_FRAMEBUFFER_OPERATION: "GL_INVALID_FRAMEBUFFER_OPERATION",
        gl.GL_OUT_OF_MEMORY: "GL_OUT_OF_MEMORY",
        gl.GL_STACK_UNDERFLOW: "GL_STACK_UNDERFLOW",
        gl.GL_STACK_OVERFLOW: "GL_STACK_OVERFLOW",
    }

    def __init__(self, gc_mode: str = "context_gc"):
        self.limits = Limits(self)
        self._gl_version = (self.limits.MAJOR_VERSION, self.limits.MINOR_VERSION)
        HLContext.activate(self)
        # Texture unit we use when doing operations on textures to avoid
        # affecting currently bound textures in the first units
        self.default_texture_unit: int = self.limits.MAX_TEXTURE_IMAGE_UNITS - 1
        self.stats: ContextStats = ContextStats(warn_threshold=1000)

        # Hardcoded states
        # This should always be enabled
        gl.glEnable(gl.GL_TEXTURE_CUBE_MAP_SEAMLESS)
        # Set primitive restart index to -1 by default
        gl.glEnable(gl.GL_PRIMITIVE_RESTART)
        self._primitive_restart_index = -1
        self.primitive_restart_index = self._primitive_restart_index

        # We enable scissor testing by default.
        # This is always set to the same value as the viewport
        # to avoid background color affecting areas outside the viewport
        gl.glEnable(gl.GL_SCISSOR_TEST)

        # States
        self._blend_func = self.BLEND_DEFAULT
        self._point_size = 1.0
        self._flags: Set[int] = set()

        # Context GC as default. We need to call Context.gc() to free opengl resources
        self._gc_mode = "context_gc"
        self.gc_mode = gc_mode
        #: Collected objects to gc when gc_mode is "context_gc"
        self.objects: Deque[Any] = deque()

    @property
    def gl_version(self) -> Tuple[int, int]:
        """
        The OpenGL version as a 2 component tuple
        :type: tuple (major, minor) version
        """
        return self._gl_version

    def gc(self) -> int:
        """
        Run garbage collection of OpenGL objects for this context.
        This is only needed when ``gc_mode`` is ``context_gc``.
        :return: The number of resources destroyed
        :rtype: int
        """
        # Loop the array until all objects are gone.
        # Deleting one object might add new ones so we need
        # to loop until the deque is empty
        num_objects = 0

        while len(self.objects):
            obj = self.objects.popleft()
            obj.delete()
            num_objects += 1

        return num_objects

    @property
    def gc_mode(self) -> str:
        """
        Set the garbage collection mode for OpenGL resources.
        Supported modes are:
            # default: Auto 
            ctx.gc_mode = "auto"
            # Defer garbage collection until ctx.gc() is called
            # This can be useful to enforce the main thread to
            # run garbage collection of opengl resources
            ctx.gc_mode = "context_gc"            
        """
        return self._gc_mode

    @gc_mode.setter
    def gc_mode(self, value: str):
        modes = ["auto", "context_gc"]
        if value not in modes:
            raise ValueError("Unsupported gc_mode. Supported modes are:", modes)
        self._gc_mode = value

    @property
    def error(self) -> Union[str, None]:
        """Check OpenGL error
        Returns a string representation of the occurring error
        or ``None`` of no errors has occurred.
        Example::
            err = ctx.error
            if err:
                raise RuntimeError("OpenGL error: {err}")
        :type: str
        """
        err = gl.glGetError()
        if err == gl.GL_NO_ERROR:
            return None

        return self._errors.get(err, "GL_UNKNOWN_ERROR")

    @classmethod
    def activate(cls, ctx: "HLContext"):
        """Mark a context as the currently active one"""
        cls.active = ctx

    def enable(self, *flags):
        """
        Enables one or more context flags::
            # Single flag
            ctx.enable(ctx.BLEND)
            # Multiple flags
            ctx.enable(ctx.DEPTH_TEST, ctx.CULL_FACE)
        """
        self._flags.update(flags)

        for flag in flags:
            gl.glEnable(flag)

    def enable_only(self, *args):
        """
        Enable only some flags. This will disable all other flags.
        This is a simple way to ensure that context flag states
        are not lingering from other sections of your code base::
            # Ensure all flags are disabled (enable no flags)
            ctx.enable_only()
            # Make sure only blending is enabled
            ctx.enable_only(ctx.BLEND)
            # Make sure only depth test and culling is enabled
            ctx.enable_only(ctx.DEPTH_TEST, ctx.CULL_FACE)        
        """
        self._flags = set(args)

        if self.BLEND in self._flags:
            gl.glEnable(self.BLEND)
        else:
            gl.glDisable(self.BLEND)

        if self.DEPTH_TEST in self._flags:
            gl.glEnable(self.DEPTH_TEST)
        else:
            gl.glDisable(self.DEPTH_TEST)

        if self.CULL_FACE in self._flags:
            gl.glEnable(self.CULL_FACE)
        else:
            gl.glDisable(self.CULL_FACE)

        if self.PROGRAM_POINT_SIZE in self._flags:
            gl.glEnable(self.PROGRAM_POINT_SIZE)
        else:
            gl.glDisable(self.PROGRAM_POINT_SIZE)

    @contextmanager
    def enabled(self, *flags):
        """
        Temporarily change enabled flags::
            with ctx.enabled(ctx.BLEND, ctx.CULL_FACE):
                # Render something
        """
        old_flags = self._flags
        self.enable(*flags)
        try:
            yield
        finally:
            self.enable(*old_flags)

    @contextmanager
    def enabled_only(self, *flags):
        """
        Temporarily change enabled flags::
            with ctx.enabled_only(ctx.BLEND, ctx.CULL_FACE):
                # Render something
        """
        old_flags = self._flags
        self.enable_only(*flags)
        try:
            yield
        finally:
            self.enable_only(*old_flags)

    def disable(self, *args):
        """
        Disable one or more context flags::
            # Single flag
            ctx.disable(ctx.BLEND)
            # Multiple flags
            ctx.disable(ctx.DEPTH_TEST, ctx.CULL_FACE)
        """
        self._flags -= set(args)

        for flag in args:
            gl.glDisable(flag)

    def is_enabled(self, flag) -> bool:
        """
        Check if a context flag is enabled
        :type: bool
        """
        return flag in self._flags

    @property
    def blend_func(self) -> Tuple[int, int]:
        """
        Get or the blend function::
            ctx.blend_func = ctx.ONE, ctx.ONE
        :type: tuple (src, dst)
        """
        return self._blend_func

    @blend_func.setter
    def blend_func(self, value: Tuple[int, int]):
        self._blend_func = value
        gl.glBlendFunc(value[0], value[1])

    # def blend_equation(self)
    # def front_face(self)
    # def cull_face(self)

    @property
    def patch_vertices(self) -> int:
        """
        Get or set number of vertices that will be used to make up a single patch primitive.
        Patch primitives are consumed by the tessellation control shader (if present)
        and subsequently used for tessellation.
        :type: int
        """
        value = c_int()
        gl.glGetIntegerv(gl.GL_PATCH_VERTICES, value)
        return value.value

    @patch_vertices.setter
    def patch_vertices(self, value: int):
        if not isinstance(value, int):
            raise TypeError("patch_vertices must be an integer")

        gl.glPatchParameteri(gl.GL_PATCH_VERTICES, value)

    @property
    def point_size(self) -> float:
        """float: Get or set the point size."""
        return self._point_size

    @point_size.setter
    def point_size(self, value: float):
        gl.glPointSize(self._point_size)
        self._point_size = value

    @property
    def primitive_restart_index(self) -> int:
        """Get or set the primitive restart index. Default is -1"""
        return self._primitive_restart_index

    @primitive_restart_index.setter
    def primitive_restart_index(self, value: int):
        self._primitive_restart_index = value
        gl.glPrimitiveRestartIndex(value)

    def finish(self) -> None:
        """
        Wait until all OpenGL rendering commands are completed.
        This function will actually stall until all work is done
        and may have severe performance implications.
        """
        gl.glFinish()

    def flush(self):
        """
        A suggestion to the driver to execute all the queued
        drawing calls even if the queue is not full yet.
        This is not a blocking call and only a suggestion.
        This can potentially be used for speedups when
        we don't have anything else to render.
        """
        gl.glFlush()

    # Various utility methods

    # --- Resource methods ---

    def buffer(
        self, *, data: Optional[Any] = None, reserve: int = 0, usage: str = "static"
    ) -> HLBuffer:
        """Create a new OpenGL Buffer object.
        :param Any data: The buffer data, This can be ``bytes`` or an object supporting the buffer protocol.
        :param int reserve: The number of bytes reserve
        :param str usage: Buffer usage. 'static', 'dynamic' or 'stream'
        :rtype: :py:class:`~arcade.gl.Buffer`
        """
        # create_with_size
        return HLBuffer(self, data, reserve=reserve, usage=usage)

# def framebuffer(
#         self,
#         *,
#         color_attachments: Union[HLTexture, List[HLTexture]] = None,
#         depth_attachment: HLTexture = None
#     ) -> HLFramebuffer:
#         """Create a Framebuffer.
#         :param List[arcade.gl.Texture] color_attachments: List of textures we want to render into
#         :param arcade.gl.Texture depth_attachment: Depth texture
#         :rtype: :py:class:`~arcade.gl.Framebuffer`
#         """
#         return HLFramebuffer(
#             self, color_attachments=color_attachments, depth_attachment=depth_attachment
#         )

class ContextStats:
    def __init__(self, warn_threshold=100):
        self.warn_threshold = warn_threshold
        # (created, freed)
        self.texture = (0, 0)
        self.framebuffer = (0, 0)
        self.buffer = (0, 0)
        self.program = (0, 0)
        self.vertex_array = (0, 0)
        self.geometry = (0, 0)
        self.compute_shader = (0, 0)
        self.query = (0, 0)

    def incr(self, key):
        created, freed = getattr(self, key)
        setattr(self, key, (created + 1, freed))
        if created % self.warn_threshold == 0 and created > 0:
            LOG.debug(
                "%s allocations passed threshold (%s) [created = %s] [freed = %s] [active = %s]",
                key,
                self.warn_threshold,
                created,
                freed,
                created - freed,
            )

    def decr(self, key):
        created, freed = getattr(self, key)
        setattr(self, key, (created, freed + 1))


class Limits:
    """OpenGL Limitations"""

    def __init__(self, ctx):
        self._ctx = ctx
        #: Minor version number of the OpenGL API supported by the current context
        self.MINOR_VERSION = self.get(gl.GL_MINOR_VERSION)
        #: Major version number of the OpenGL API supported by the current context.
        self.MAJOR_VERSION = self.get(gl.GL_MAJOR_VERSION)
        self.VENDOR = self.get_str(gl.GL_VENDOR)
        self.RENDERER = self.get_str(gl.GL_RENDERER)
        #: Value indicating the number of sample buffers associated with the framebuffer
        self.SAMPLE_BUFFERS = self.get(gl.GL_SAMPLE_BUFFERS)
        #: An estimate of the number of bits of subpixel resolution
        #: that are used to position rasterized geometry in window coordinates
        self.SUBPIXEL_BITS = self.get(gl.GL_SUBPIXEL_BITS)
        #: A mask value indicating what context profile is used (core, compat etc.)
        self.CONTEXT_PROFILE_MASK = self.get(gl.GL_CONTEXT_PROFILE_MASK)
        #: Minimum required alignment for uniform buffer sizes and offset
        self.UNIFORM_BUFFER_OFFSET_ALIGNMENT = self.get(
            gl.GL_UNIFORM_BUFFER_OFFSET_ALIGNMENT
        )
        #: Value indicates the maximum number of layers allowed in an array texture, and must be at least 256
        self.MAX_ARRAY_TEXTURE_LAYERS = self.get(gl.GL_MAX_ARRAY_TEXTURE_LAYERS)
        #: A rough estimate of the largest 3D texture that the GL can handle. The value must be at least 64
        self.MAX_3D_TEXTURE_SIZE = self.get(gl.GL_MAX_3D_TEXTURE_SIZE)
        #: Maximum number of color attachments in a framebuffer
        self.MAX_COLOR_ATTACHMENTS = self.get(gl.GL_MAX_COLOR_ATTACHMENTS)
        #: Maximum number of samples in a color multisample texture
        self.MAX_COLOR_TEXTURE_SAMPLES = self.get(gl.GL_MAX_COLOR_TEXTURE_SAMPLES)
        #: the number of words for fragment shader uniform variables in all uniform blocks
        self.MAX_COMBINED_FRAGMENT_UNIFORM_COMPONENTS = self.get(
            gl.GL_MAX_COMBINED_FRAGMENT_UNIFORM_COMPONENTS
        )
        #: Number of words for geometry shader uniform variables in all uniform blocks
        self.MAX_COMBINED_GEOMETRY_UNIFORM_COMPONENTS = self.get(
            gl.GL_MAX_COMBINED_GEOMETRY_UNIFORM_COMPONENTS
        )
        #: Maximum supported texture image units that can be used to access texture maps from the vertex shader
        self.MAX_COMBINED_TEXTURE_IMAGE_UNITS = self.get(
            gl.GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS
        )
        #: Maximum number of uniform blocks per program
        self.MAX_COMBINED_UNIFORM_BLOCKS = self.get(gl.GL_MAX_COMBINED_UNIFORM_BLOCKS)
        #: Number of words for vertex shader uniform variables in all uniform blocks
        self.MAX_COMBINED_VERTEX_UNIFORM_COMPONENTS = self.get(
            gl.GL_MAX_COMBINED_VERTEX_UNIFORM_COMPONENTS
        )
        #: A rough estimate of the largest cube-map texture that the GL can handle
        self.MAX_CUBE_MAP_TEXTURE_SIZE = self.get(gl.GL_MAX_CUBE_MAP_TEXTURE_SIZE)
        #: Maximum number of samples in a multisample depth or depth-stencil texture
        self.MAX_DEPTH_TEXTURE_SAMPLES = self.get(gl.GL_MAX_DEPTH_TEXTURE_SAMPLES)
        #: Maximum number of simultaneous outputs that may be written in a fragment shader
        self.MAX_DRAW_BUFFERS = self.get(gl.GL_MAX_DRAW_BUFFERS)
        #: Maximum number of active draw buffers when using dual-source blending
        self.MAX_DUAL_SOURCE_DRAW_BUFFERS = self.get(gl.GL_MAX_DUAL_SOURCE_DRAW_BUFFERS)
        #: Recommended maximum number of vertex array indices
        self.MAX_ELEMENTS_INDICES = self.get(gl.GL_MAX_ELEMENTS_INDICES)
        #: Recommended maximum number of vertex array vertices
        self.MAX_ELEMENTS_VERTICES = self.get(gl.GL_MAX_ELEMENTS_VERTICES)
        #: Maximum number of components of the inputs read by the fragment shader
        self.MAX_FRAGMENT_INPUT_COMPONENTS = self.get(
            gl.GL_MAX_FRAGMENT_INPUT_COMPONENTS
        )
        #: Maximum number of individual floating-point, integer, or boolean values that can be
        #: held in uniform variable storage for a fragment shader
        self.MAX_FRAGMENT_UNIFORM_COMPONENTS = self.get(
            gl.GL_MAX_FRAGMENT_UNIFORM_COMPONENTS
        )
        #: maximum number of individual 4-vectors of floating-point, integer,
        #: or boolean values that can be held in uniform variable storage for a fragment shader
        self.MAX_FRAGMENT_UNIFORM_VECTORS = self.get(gl.GL_MAX_FRAGMENT_UNIFORM_VECTORS)
        #: Maximum number of uniform blocks per fragment shader.
        self.MAX_FRAGMENT_UNIFORM_BLOCKS = self.get(gl.GL_MAX_FRAGMENT_UNIFORM_BLOCKS)
        #: Maximum number of components of inputs read by a geometry shader
        self.MAX_GEOMETRY_INPUT_COMPONENTS = self.get(
            gl.GL_MAX_GEOMETRY_INPUT_COMPONENTS
        )
        #: Maximum number of components of outputs written by a geometry shader
        self.MAX_GEOMETRY_OUTPUT_COMPONENTS = self.get(
            gl.GL_MAX_GEOMETRY_OUTPUT_COMPONENTS
        )
        #: Maximum supported texture image units that can be used to access texture maps from the geometry shader
        self.MAX_GEOMETRY_TEXTURE_IMAGE_UNITS = self.get(
            gl.GL_MAX_GEOMETRY_TEXTURE_IMAGE_UNITS
        )
        #: Maximum number of uniform blocks per geometry shader
        self.MAX_GEOMETRY_UNIFORM_BLOCKS = self.get(gl.GL_MAX_GEOMETRY_UNIFORM_BLOCKS)
        #: Maximum number of individual floating-point, integer, or boolean values that can
        #: be held in uniform variable storage for a geometry shader
        self.MAX_GEOMETRY_UNIFORM_COMPONENTS = self.get(
            gl.GL_MAX_GEOMETRY_UNIFORM_COMPONENTS
        )
        #: Maximum number of samples supported in integer format multisample buffers
        self.MAX_INTEGER_SAMPLES = self.get(gl.GL_MAX_INTEGER_SAMPLES)
        #: Maximum samples for a framebuffer
        self.MAX_SAMPLES = self.get(gl.GL_MAX_SAMPLES)
        #: A rough estimate of the largest rectangular texture that the GL can handle
        self.MAX_RECTANGLE_TEXTURE_SIZE = self.get(gl.GL_MAX_RECTANGLE_TEXTURE_SIZE)
        #: Maximum supported size for renderbuffers
        self.MAX_RENDERBUFFER_SIZE = self.get(gl.GL_MAX_RENDERBUFFER_SIZE)
        #: Maximum number of sample mask words
        self.MAX_SAMPLE_MASK_WORDS = self.get(gl.GL_MAX_SAMPLE_MASK_WORDS)
        #: Maximum number of texels allowed in the texel array of a texture buffer object
        self.MAX_TEXTURE_BUFFER_SIZE = self.get(gl.GL_MAX_TEXTURE_BUFFER_SIZE)
        #: Maximum number of uniform buffer binding points on the context
        self.MAX_UNIFORM_BUFFER_BINDINGS = self.get(gl.GL_MAX_UNIFORM_BUFFER_BINDINGS)
        #: Maximum number of uniform buffer binding points on the context
        self.MAX_UNIFORM_BUFFER_BINDINGS = self.get(gl.GL_MAX_UNIFORM_BUFFER_BINDINGS)
        #: The value gives a rough estimate of the largest texture that the GL can handle
        self.MAX_TEXTURE_SIZE = self.get(gl.GL_MAX_TEXTURE_SIZE)
        #: Maximum number of uniform buffer binding points on the context
        self.MAX_UNIFORM_BUFFER_BINDINGS = self.get(gl.GL_MAX_UNIFORM_BUFFER_BINDINGS)
        #: Maximum size in basic machine units of a uniform block
        self.MAX_UNIFORM_BLOCK_SIZE = self.get(gl.GL_MAX_UNIFORM_BLOCK_SIZE)
        #: The number 4-vectors for varying variables
        self.MAX_VARYING_VECTORS = self.get(gl.GL_MAX_VARYING_VECTORS)
        #: Maximum number of 4-component generic vertex attributes accessible to a vertex shader.
        self.MAX_VERTEX_ATTRIBS = self.get(gl.GL_MAX_VERTEX_ATTRIBS)
        #: Maximum supported texture image units that can be used to access texture maps from the vertex shader.
        self.MAX_VERTEX_TEXTURE_IMAGE_UNITS = self.get(
            gl.GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS
        )
        #: Maximum number of individual floating-point, integer, or boolean values that
        #: can be held in uniform variable storage for a vertex shader
        self.MAX_VERTEX_UNIFORM_COMPONENTS = self.get(
            gl.GL_MAX_VERTEX_UNIFORM_COMPONENTS
        )
        #: Maximum number of 4-vectors that may be held in uniform variable storage for the vertex shader
        self.MAX_VERTEX_UNIFORM_VECTORS = self.get(gl.GL_MAX_VERTEX_UNIFORM_VECTORS)
        #: Maximum number of components of output written by a vertex shader
        self.MAX_VERTEX_OUTPUT_COMPONENTS = self.get(gl.GL_MAX_VERTEX_OUTPUT_COMPONENTS)
        #: Maximum number of uniform blocks per vertex shader.
        self.MAX_VERTEX_UNIFORM_BLOCKS = self.get(gl.GL_MAX_VERTEX_UNIFORM_BLOCKS)
        # self.MAX_VERTEX_ATTRIB_RELATIVE_OFFSET = self.get(gl.GL_MAX_VERTEX_ATTRIB_RELATIVE_OFFSET)
        # self.MAX_VERTEX_ATTRIB_BINDINGS = self.get(gl.GL_MAX_VERTEX_ATTRIB_BINDINGS)
        self.MAX_TEXTURE_IMAGE_UNITS = self.get(gl.GL_MAX_TEXTURE_IMAGE_UNITS)
        # TODO: Missing in pyglet
        self.MAX_TEXTURE_MAX_ANISOTROPY = self.get_float(gl.GL_MAX_TEXTURE_MAX_ANISOTROPY)
        self.MAX_VIEWPORT_DIMS = self.get_int_tuple(gl.GL_MAX_VIEWPORT_DIMS, 2)

        err = self._ctx.error
        if err:
            from warnings import warn

            warn("Error happened while querying of limits. Moving on ..")

    def get_int_tuple(self, enum: gl.GLenum, length: int):
        """Get an enum as an int tuple"""
        values = (c_int * length)()
        gl.glGetIntegerv(enum, values)
        return tuple(values)

    def get(self, enum: gl.GLenum) -> int:
        """Get an integer limit"""
        value = c_int()
        gl.glGetIntegerv(enum, value)
        return value.value

    def get_float(self, enum: gl.GLenum) -> float:
        """Get a float limit"""
        value = c_float()
        gl.glGetFloatv(enum, value)
        return value.value

    def get_str(self, enum: gl.GLenum) -> str:
        """Get a string limit"""
        return cast(gl.glGetString(enum), c_char_p).value.decode()  # type: ignoree
