from ctypes import c_int
from contextlib import contextmanager
from typing import Optional, Tuple, List, TYPE_CHECKING
import weakref


from pyglet import gl

from .hltexture import HLTexture
from arcade.gl.types import pixel_formats

if TYPE_CHECKING:  # handle import cycle caused by type hinting
    from .hlcontext import HLContext


class HLFramebuffer:
    """
    An offscreen render target also called a Framebuffer Object in OpenGL.
    This implementation is using texture attachments. When creating a
    Framebuffer we supply it with textures we want our scene rendered into.
    The advantage of using texture attachments is the ability we get
    to keep working on the contents of the framebuffer.
    The best way to create framebuffer is through :py:meth:`arcade.gl.Context.framebuffer`::
        # Create a 100 x 100 framebuffer with one attachment
        ctx.framebuffer(color_attachments=[ctx.texture((100, 100), components=4)])
        # Create a 100 x 100 framebuffer with two attachments
        # Shaders can be configured writing to the different layers
        ctx.framebuffer(
            color_attachments=[
                ctx.texture((100, 100), components=4),
                ctx.texture((100, 100), components=4),
            ]
        )
    :param Context ctx: The context this framebuffer belongs to
    :param List[arcade.gl.Texture] color_attachments: List of color attachments.
    :param arcade.gl.Texture depth_attachment: A depth attachment (optional)
    """

    #: Is this the default framebuffer? (window buffer)
    is_default = False
    __slots__ = (
        "_ctx",
        "_glo",
        "_width",
        "_height",
        "_color_attachments",
        "_depth_attachment",
        "_samples",
        "_viewport",
        "_scissor",
        "_depth_mask",
        "_draw_buffers",
        "_prev_fbo",
        "__weakref__",
    )

    def __init__(
        self, ctx: "HLContext", *, color_attachments=None, depth_attachment=None
    ):
        self._glo = fbo_id = gl.GLuint()  # The OpenGL alias/name
        self._ctx = ctx
        if not color_attachments:
            raise ValueError("Framebuffer must at least have one color attachment")

        self._color_attachments = (
            color_attachments
            if isinstance(color_attachments, list)
            else [color_attachments]
        )
        self._depth_attachment = depth_attachment
        self._samples = 0  # Leaving this at 0 for future sample support
        self._depth_mask = True  # Determines if the depth buffer should be affected
        self._prev_fbo = None

        # Create the framebuffer object
        gl.glGenFramebuffers(1, self._glo)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._glo)

        # Ensure all attachments have the same size.
        # OpenGL do actually support different sizes,
        # but let's keep this simple with high compatibility.
        self._width, self._height = self._detect_size()

        # Attach textures to it
        for i, tex in enumerate(self._color_attachments):
            # TODO: Possibly support attaching a specific mipmap level
            #       but we can read from specific mip levels from shaders.
            gl.glFramebufferTexture2D(
                gl.GL_FRAMEBUFFER,
                gl.GL_COLOR_ATTACHMENT0 + i,
                tex._target,
                tex.glo,
                0,  # Level 0
            )

        if self.depth_attachment:
            gl.glFramebufferTexture2D(
                gl.GL_FRAMEBUFFER,
                gl.GL_DEPTH_ATTACHMENT,
                self.depth_attachment._target,
                self.depth_attachment.glo,
                0,
            )

        # Ensure the framebuffer is sane!
        self._check_completeness()

        # Set up draw buffers. This is simply a prepared list of attachments enums
        # we use in the use() method to activate the different color attachment layers
        layers = [
            gl.GL_COLOR_ATTACHMENT0 + i for i, _ in enumerate(self._color_attachments)
        ]
        # pyglet wants this as a ctypes thingy, so let's prepare it
        self._draw_buffers = (gl.GLuint * len(layers))(*layers)


        if self._ctx.gc_mode == "auto" and not self.is_default:
            weakref.finalize(self, HLFramebuffer.delete_glo, ctx, fbo_id)

        self.ctx.stats.incr("framebuffer")

    def __del__(self):
        # Intercept garbage collection if we are using Context.gc()
        if self._ctx.gc_mode == "context_gc" and not self.is_default and self._glo.value > 0:
            self._ctx.objects.append(self)

    @property
    def glo(self) -> gl.GLuint:
        """
        The OpenGL id/name of the framebuffer
        :type: GLuint
        """
        return self._glo

    @property
    def ctx(self) -> "HLContext":
        """
        The context this object belongs to.
        :type: :py:class:`arcade.gl.Context`
        """
        return self._ctx

    @property
    def width(self) -> int:
        """
        The width of the framebuffer in pixels
        :type: int
        """
        return self._width

    @property
    def height(self) -> int:
        """
        The height of the framebuffer in pixels
        :type: int
        """
        return self._height

    @property
    def size(self) -> Tuple[int, int]:
        """
        Size as a ``(w, h)`` tuple
        :type: tuple (int, int)
        """
        return self._width, self._height

    @property
    def samples(self) -> int:
        """
        Number of samples (MSAA)
        :type: int
        """
        return self._samples

    @property
    def color_attachments(self) -> List[HLTexture]:
        """
        A list of color attachments
        :type: list of :py:class:`arcade.gl.Texture`
        """
        return self._color_attachments

    @property
    def depth_attachment(self) -> HLTexture:
        """
        Depth attachment
        :type: :py:class:`arcade.gl.Texture`
        """
        return self._depth_attachment

    @property
    def depth_mask(self) -> bool:
        """
        Get or set the depth mask (default: ``True``).
        It determines if depth values should be written
        to the depth texture when depth testing is enabled.
        The depth mask value is persistent all will automatically
        be applies every time the framebuffer is bound.
        :type: bool
        """
        return self._depth_mask

    @depth_mask.setter
    def depth_mask(self, value: bool):
        self._depth_mask = value

    def __enter__(self):
        self._prev_fbo = self._ctx.active_framebuffer
        self.use()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._prev_fbo.use()

    @contextmanager
    def activate(self):
        """Context manager for binding the framebuffer.
        Unlike the default context manager in this class
        this support nested framebuffer binding.
        """
        prev_fbo = self._ctx.active_framebuffer
        try:
            self.use()
            yield self
        finally:
            prev_fbo.use()

    def use(self, *, force: bool = False):
        """Bind the framebuffer making it the target of all rendering commands
        :param bool force: Force the framebuffer binding even if the system
                           already believes it's already bound.
        """
        self._use(force=force)
        self._ctx.active_framebuffer = self

    def _use(self, *, force: bool = False):
        """Internal use that do not change the global active framebuffer"""
        if self.ctx.active_framebuffer == self and not force:
            return

        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._glo)

        # NOTE: gl.glDrawBuffer(GL_NONE) if no texture attachments (future)
        # NOTE: Default framebuffer currently has this set to None
        if self._draw_buffers:
            gl.glDrawBuffers(len(self._draw_buffers), self._draw_buffers)

        gl.glDepthMask(self._depth_mask)

    def clear(
        self,
        color=(0.0, 0.0, 0.0, 0.0),
        *,
        depth: float = 1.0,
        normalized: bool = False,
        viewport: Tuple[int, int, int, int] = None,
    ):
        """
        Clears the framebuffer::
            # Clear framebuffer using the color red in normalized form
            fbo.clear(color=(1.0, 0.0, 0.0, 1.0), normalized=True)
            # Clear the framebuffer using arcade's colors (not normalized)
            fb.clear(color=arcade.color.WHITE)
        If the background color is an ``RGB`` value instead of ``RGBA```
        we assume alpha value 255.
        :param tuple color: A 3 or 4 component tuple containing the color
        :param float depth: Value to clear the depth buffer (unused)
        :param bool normalized: If the color values are normalized or not
        :param Tuple[int, int, int, int] viewport: The viewport range to clear
        """
        with self.activate():

            if normalized:
                # If the colors are already normalized we can pass them right in
                if len(color) == 3:
                    gl.glClearColor(*color, 1.0)
                else:
                    gl.glClearColor(*color)
            else:
                # OpenGL wants normalized colors (0.0 -> 1.0)
                if len(color) == 3:
                    gl.glClearColor(color[0] / 255, color[1] / 255, color[2] / 255, 1.0)
                else:
                    gl.glClearColor(
                        color[0] / 255, color[1] / 255, color[2] / 255, color[3] / 255
                    )

            if self.depth_attachment:
                gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
            else:
                gl.glClear(gl.GL_COLOR_BUFFER_BIT)

    def read(
        self, *, viewport=None, components=3, attachment=0, dtype="f1"
    ) -> bytearray:
        """
        Read framebuffer pixels
        :param Tuple[int,int,int,int] viewport: The x, y, with, height to read
        :param int components:
        :param int attachment: The attachment id to read from
        :param str dtype: The data type to read
        :return: pixel data as a bytearray
        """
        # TODO: use texture attachment info to determine read format?
        try:
            frmt = pixel_formats[dtype]
            base_format = frmt[0][components]
            pixel_type = frmt[2]
        except Exception:
            raise ValueError(f"Invalid dtype '{dtype}'")

        with self:
            # Configure attachment to read from
            # gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0 + attachment)
            if viewport:
                x, y, width, height = viewport
            else:
                x, y, width, height = 0, 0, self._width, self._height
            data = (gl.GLubyte * (components * width * height))(0)
            gl.glReadPixels(x, y, width, height, base_format, pixel_type, data)

        return bytearray(data)

    def resize(self):
        """
        Detects size changes in attachments.
        This will reset the viewport to ``0, 0, width, height``.
        """
        self._width, self._height = self._detect_size()

    def delete(self):
        """
        Destroy the underlying OpenGL resource.
        Don't use this unless you know exactly what you are doing.
        """
        HLFramebuffer.delete_glo(self._ctx, self._glo)
        self._glo.value = 0

    @staticmethod
    def delete_glo(ctx, framebuffer_id):
        """
        Destroys the framebuffer object
        :param ctx: OpenGL context
        :param framebuffer_id: Framebuffer to destroy (glo)
        """
        if gl.current_context is None:
            return

        gl.glDeleteFramebuffers(1, framebuffer_id)
        ctx.stats.decr("framebuffer")

    def _detect_size(self) -> Tuple[int, int]:
        """Detect the size of the framebuffer based on the attachments"""
        expected_size = (
            self._color_attachments[0]
            if self._color_attachments
            else self._depth_attachment
        ).size
        for layer in [*self._color_attachments, self._depth_attachment]:
            if layer and layer.size != expected_size:
                raise ValueError(
                    "All framebuffer attachments should have the same size"
                )
        return expected_size

    @staticmethod
    def _check_completeness() -> None:
        """
        Checks the completeness of the framebuffer.
        If the framebuffer is not complete, we cannot continue.
        """
        # See completeness rules : https://www.khronos.org/opengl/wiki/Framebuffer_Object
        states = {
            gl.GL_FRAMEBUFFER_UNSUPPORTED: "Framebuffer unsupported. Try another format.",
            gl.GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT: "Framebuffer incomplete attachment.",
            gl.GL_FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT: "Framebuffer missing attachment.",
            gl.GL_FRAMEBUFFER_INCOMPLETE_DIMENSIONS_EXT: "Framebuffer unsupported dimension.",
            gl.GL_FRAMEBUFFER_INCOMPLETE_FORMATS_EXT: "Framebuffer incomplete formats.",
            gl.GL_FRAMEBUFFER_INCOMPLETE_DRAW_BUFFER: "Framebuffer incomplete draw buffer.",
            gl.GL_FRAMEBUFFER_INCOMPLETE_READ_BUFFER: "Framebuffer incomplete read buffer.",
            gl.GL_FRAMEBUFFER_COMPLETE: "Framebuffer is complete.",
        }

        status = gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER)
        if status != gl.GL_FRAMEBUFFER_COMPLETE:
            raise ValueError(
                "Framebuffer is incomplete. {}".format(
                    states.get(status, "Unknown error")
                )
            )

    def __repr__(self):
        return "<Framebuffer glo={}>".format(self._glo.value)


