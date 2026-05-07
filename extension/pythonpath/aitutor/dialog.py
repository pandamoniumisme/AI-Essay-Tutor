"""AWT dialogs built programmatically via UnoControlDialogModel.

Phase 1 dialogs:
- :class:`TranscribeInputDialog` -- collects language + question + essay files.
- :class:`ProgressDialog` -- modal "working..." dialog that polls a server-side
  job every 3 seconds and updates a status line, so LO does not appear frozen.
- :func:`show_text_result` -- displays multi-line OCR output.
"""
from __future__ import annotations

import threading

import uno
import unohelper
from com.sun.star.awt import Rectangle  # noqa: F401  (registered via uno)
from com.sun.star.awt import XActionListener
from com.sun.star.awt.MessageBoxButtons import BUTTONS_OK
from com.sun.star.awt.MessageBoxType import ERRORBOX, INFOBOX
from com.sun.star.beans import PropertyValue, XPropertyChangeListener

from aitutor import client
from aitutor.log import get_logger

log = get_logger(__name__)


# --- Generic dialog helpers ----------------------------------------------

def _smgr(ctx):
    return ctx.ServiceManager


def _create(ctx, service_name):
    return _smgr(ctx).createInstanceWithContext(service_name, ctx)


def _toolkit(ctx):
    return _create(ctx, "com.sun.star.awt.Toolkit")


def _make_property_values(d: dict) -> tuple[PropertyValue, ...]:
    out = []
    for k, v in d.items():
        p = PropertyValue()
        p.Name = k
        p.Value = v
        out.append(p)
    return tuple(out)


def show_message(ctx, title: str, body: str, kind=INFOBOX) -> None:
    parent = _toolkit(ctx).createMessageBox(
        None, kind, BUTTONS_OK, title, body,
    ) if False else None  # unused branch; LO requires a peer. Use the alt path below.
    # The createMessageBox API path varies across LO versions; simplest reliable
    # path is via the desktop's current window peer.
    desktop = _create(ctx, "com.sun.star.frame.Desktop")
    frame = desktop.getCurrentFrame()
    peer = frame.getContainerWindow() if frame else None
    box = _toolkit(ctx).createMessageBox(peer, kind, BUTTONS_OK, title, body)
    box.execute()


def show_error(ctx, title: str, body: str) -> None:
    show_message(ctx, title, body, kind=ERRORBOX)


# --- Input dialog: language + question file + essay file -----------------

class TranscribeInputDialog:
    """Encapsulates the input dialog so callbacks can mutate its state."""

    LANGUAGE_EN = "en"
    LANGUAGE_ZH = "zh-Hans"

    MAX_PAGES = 4
    """Hard cap on pages per side. PSLE essays rarely exceed 3 pages; 4 leaves
    a margin. Increase this constant if a real essay needs more."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.language = self.LANGUAGE_EN
        # Per-slot paths: index 0 = page 1, etc. None = empty.
        self.question_paths: list[str | None] = [None] * self.MAX_PAGES
        self.essay_paths: list[str | None] = [None] * self.MAX_PAGES
        self.debug = False
        self._submitted = False
        self._dialog = None

    def execute(self) -> tuple[str, list[str], list[str], bool] | None:
        """Show the dialog. Returns (language, question_paths, essay_paths,
        debug) on Submit (paths are non-empty, in user-chosen page order;
        debug is True if the user ticked the debug checkbox). Returns None
        on Cancel."""
        ctx = self.ctx
        smgr = _smgr(ctx)

        model = smgr.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialogModel", ctx
        )
        # Dialog shape sized for MAX_PAGES=4 per side, plus a debug row at the bottom.
        model.Width = 360
        model.Height = 308
        model.Title = "Compo Tutor"

        # --- Language group ---
        self._add_label(model, "lang_lbl", 6, 6, 60, 10, "Language:")
        rb_en = self._add(model, "com.sun.star.awt.UnoControlRadioButtonModel",
                          "lang_en", 70, 4, 80, 12)
        rb_en.Label = "English"
        rb_en.State = 1  # selected by default
        rb_zh = self._add(model, "com.sun.star.awt.UnoControlRadioButtonModel",
                          "lang_zh", 160, 4, 180, 12)
        rb_zh.Label = "Simplified Chinese (简体中文)"
        rb_zh.State = 0

        # --- Question pages section ---
        self._add_label(model, "q_section", 6, 26, 200, 10,
                        "Question pages (in order):")
        for i in range(self.MAX_PAGES):
            self._add_page_row(model, "q", i, base_y=40 + i * 20)

        # --- Essay pages section ---
        self._add_label(model, "e_section", 6, 132, 200, 10,
                        "Essay pages (in order):")
        for i in range(self.MAX_PAGES):
            self._add_page_row(model, "e", i, base_y=146 + i * 20)

        # --- Hint ---
        hint = self._add_label(
            model, "hint", 6, 232, 348, 24,
            "One image per page slot. The next slot appears after you fill the "
            "current one, so the order you click matches the order in your essay.\n"
            "After Start, LO will appear FROZEN for 30-90 seconds per page."
        )
        hint.MultiLine = True

        # --- Debug checkbox (skip LLM runs by reusing cached outputs) ---
        chk = self._add(model, "com.sun.star.awt.UnoControlCheckBoxModel",
                        "chk_debug", 6, 263, 348, 12)
        chk.Label = ("Debug: reuse cached outputs from last run "
                     "(skips OCR/grading if cache exists)")
        chk.State = 0

        # --- Bottom row: Cancel / Start ---
        self._add_button(model, "btn_cancel", 218, 281, 60, 20, "Cancel",
                         pushtype=2)
        btn_ok = self._add_button(model, "btn_ok", 286, 281, 68, 20, "Start",
                                  pushtype=0)
        btn_ok.DefaultButton = True

        # --- Build the dialog control + listeners ---
        dlg = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
        dlg.setModel(model)
        dlg.createPeer(_toolkit(ctx), None)
        self._dialog = dlg

        # Wire up per-slot listeners.
        for i in range(self.MAX_PAGES):
            dlg.getControl(f"q_browse_{i}").addActionListener(_FnActionListener(
                lambda ev, idx=i: self._on_pick("question", idx)))
            dlg.getControl(f"e_browse_{i}").addActionListener(_FnActionListener(
                lambda ev, idx=i: self._on_pick("essay", idx)))
            dlg.getControl(f"q_clear_{i}").addActionListener(_FnActionListener(
                lambda ev, idx=i: self._on_clear_slot("question", idx)))
            dlg.getControl(f"e_clear_{i}").addActionListener(_FnActionListener(
                lambda ev, idx=i: self._on_clear_slot("essay", idx)))

        dlg.getControl("btn_ok").addActionListener(_FnActionListener(
            lambda ev: self._on_submit()))
        dlg.getControl("btn_cancel").addActionListener(_FnActionListener(
            lambda ev: dlg.endExecute()))

        rb_en.addPropertyChangeListener("State", _FnPropertyListener(
            lambda ev: self._on_lang_change(self.LANGUAGE_EN, ev.NewValue)))
        rb_zh.addPropertyChangeListener("State", _FnPropertyListener(
            lambda ev: self._on_lang_change(self.LANGUAGE_ZH, ev.NewValue)))

        # Initial visibility: only page 1 of each side is visible.
        self._refresh_visibility()

        dlg.execute()
        dlg.dispose()

        if not self._submitted:
            return None
        q = [p for p in self.question_paths if p]
        e = [p for p in self.essay_paths if p]
        return (self.language, q, e, self.debug)

    # --- Slot construction ---

    def _add_page_row(self, model, side: str, idx: int, base_y: int) -> None:
        """One row per page: 'Page N:' label, path edit, Browse..., Clear."""
        prefix = side  # 'q' or 'e'
        page_no = idx + 1
        self._add_label(model, f"{prefix}_lbl_{idx}",
                        6, base_y + 2, 36, 10, f"Page {page_no}:")
        edit = self._add(model, "com.sun.star.awt.UnoControlEditModel",
                         f"{prefix}_path_{idx}", 44, base_y, 200, 14)
        edit.ReadOnly = True
        self._add_button(model, f"{prefix}_browse_{idx}",
                         252, base_y, 56, 14, "Browse...")
        self._add_button(model, f"{prefix}_clear_{idx}",
                         312, base_y, 42, 14, "Clear")

    # --- Callbacks ---

    def _on_pick(self, side: str, idx: int) -> None:
        path = _pick_image(self.ctx, f"Choose {side} page {idx + 1}")
        if not path:
            return
        slots = self.question_paths if side == "question" else self.essay_paths
        slots[idx] = path
        self._update_slot_text(side, idx, path)
        self._refresh_visibility()

    def _on_clear_slot(self, side: str, idx: int) -> None:
        """Clear slot ``idx`` AND all subsequent slots on this side. Keeps the
        no-gaps invariant: a non-empty page slot is always preceded by
        non-empty earlier slots."""
        slots = self.question_paths if side == "question" else self.essay_paths
        for j in range(idx, self.MAX_PAGES):
            slots[j] = None
            self._update_slot_text(side, j, "")
        self._refresh_visibility()

    def _update_slot_text(self, side: str, idx: int, path: str) -> None:
        prefix = "q" if side == "question" else "e"
        ctrl = self._dialog.getControl(f"{prefix}_path_{idx}")
        if path:
            ctrl.setText(path.rsplit("\\", 1)[-1])
        else:
            ctrl.setText("")

    def _refresh_visibility(self) -> None:
        """Show slot N if and only if slot N-1 is filled (slot 0 always shown)."""
        for side, slots in (("q", self.question_paths), ("e", self.essay_paths)):
            for i in range(self.MAX_PAGES):
                visible = (i == 0) or (slots[i - 1] is not None)
                for ctrl_name in (f"{side}_lbl_{i}", f"{side}_path_{i}",
                                  f"{side}_browse_{i}", f"{side}_clear_{i}"):
                    try:
                        self._dialog.getControl(ctrl_name).setVisible(visible)
                    except Exception:
                        pass

    def _on_lang_change(self, language: str, new_state: int) -> None:
        if new_state == 1:
            self.language = language
            log.debug("language -> %s", language)

    def _on_submit(self) -> None:
        q = [p for p in self.question_paths if p]
        e = [p for p in self.essay_paths if p]
        # Read debug checkbox state.
        try:
            self.debug = bool(self._dialog.getControl("chk_debug").getState())
        except Exception:
            self.debug = False
        # In debug mode the user may legitimately have no images (they intend
        # to reuse cached outputs); skip the strict validation.
        if not self.debug and (not q or not e):
            show_error(self.ctx, "Missing files",
                       "Please add at least one question page AND at least one essay page.")
            return
        self._submitted = True
        self._dialog.endExecute()

    # --- Small helpers ---

    def _add(self, container, service_name: str, name: str,
             x: int, y: int, w: int, h: int):
        ctrl = container.createInstance(service_name)
        ctrl.PositionX = x
        ctrl.PositionY = y
        ctrl.Width = w
        ctrl.Height = h
        ctrl.Name = name
        container.insertByName(name, ctrl)
        return ctrl

    def _add_label(self, container, name: str, x: int, y: int, w: int, h: int,
                   text: str):
        c = self._add(container, "com.sun.star.awt.UnoControlFixedTextModel",
                      name, x, y, w, h)
        c.Label = text
        return c

    def _add_button(self, container, name: str, x: int, y: int, w: int, h: int,
                    text: str, pushtype: int = 0):
        c = self._add(container, "com.sun.star.awt.UnoControlButtonModel",
                      name, x, y, w, h)
        c.Label = text
        c.PushButtonType = pushtype
        return c


# --- Progress dialog: polls a server-side job every 3 s ------------------

class ProgressDialog:
    """Modal "Working..." dialog that polls /jobs/{id} every 3 seconds.

    A worker thread does the polling and updates the status line directly via
    UNO (simple ``setText`` calls are safe enough across threads in LO Python
    for our single-user case). When the job's status flips to ``done`` or
    ``error``, the worker calls ``endExecute`` to dismiss the modal.

    Returns ``(result, error)`` -- exactly one is non-None on a clean exit.
    Both are None if the user clicked Cancel.
    """

    POLL_INTERVAL_S = 3.0

    def __init__(self, ctx, job_id: str):
        self.ctx = ctx
        self.job_id = job_id
        self.result: dict | None = None
        self.error: str | None = None
        self.cancelled = False
        self._dialog = None
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def execute(self) -> tuple[dict | None, str | None]:
        smgr = _smgr(self.ctx)
        model = smgr.createInstanceWithContext(
            "com.sun.star.awt.UnoControlDialogModel", self.ctx
        )
        model.Width = 360
        model.Height = 110
        model.Title = "Compo Tutor - Working..."

        # Static informational text. We intentionally do NOT update this from
        # the polling worker thread because UNO is not thread-safe for control
        # mutation -- attempting to setText from a worker yields None / crashes.
        self._add_label(
            model, "status", 6, 6, 348, 60,
            "Transcribing your essay.\n\n"
            "This can take 60 - 180 seconds on the first run "
            "(model warm-up). Subsequent runs are faster.\n\n"
            "The result window will open automatically when done."
        )
        self._dialog_status_multiline(model)

        # Cancel button
        cancel = self._add(model, "com.sun.star.awt.UnoControlButtonModel",
                           "btn_cancel", 292, 85, 62, 18)
        cancel.Label = "Cancel"
        cancel.PushButtonType = 2  # CANCEL

        dlg = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", self.ctx)
        dlg.setModel(model)
        dlg.createPeer(_toolkit(self.ctx), None)
        self._dialog = dlg

        dlg.getControl("btn_cancel").addActionListener(
            _FnActionListener(lambda ev: self._on_cancel())
        )

        # Start the polling worker BEFORE entering the modal event loop.
        self._worker = threading.Thread(
            target=self._poll_loop, daemon=True, name=f"poll-{self.job_id}",
        )
        self._worker.start()

        dlg.execute()       # blocks here until endExecute() is called
        dlg.dispose()
        self._dialog = None

        # Stop the worker (if still alive) and let it clean up.
        self._stop.set()
        if self._worker is not None:
            self._worker.join(timeout=5)

        return (self.result, self.error)

    # --- Worker side ---

    def _poll_loop(self) -> None:
        """Poll /jobs/{id} every POLL_INTERVAL_S seconds. We do NOT touch the
        dialog UI from this thread (UNO is not thread-safe for control
        mutation). We only call endExecute() on done/error -- that single
        call is documented as thread-safe."""
        while not self._stop.is_set():
            try:
                state = client.get_job(self.job_id)
            except Exception:
                log.exception("poll failed")
                state = None

            if state is not None:
                # Log progress to extension.log so the user can tail it for live
                # status if they want, without touching UI from this thread.
                msg = state.get("message", "")
                progress = state.get("progress", 0.0) or 0.0
                log.info("job %s: %.0f%% %s", self.job_id, progress * 100, msg)

                status = state.get("status")
                if status == "done":
                    self.result = state.get("result")
                    self._end_dialog()
                    return
                if status == "error":
                    self.error = state.get("error") or msg or "unknown error"
                    self._end_dialog()
                    return

            self._stop.wait(self.POLL_INTERVAL_S)

    def _end_dialog(self) -> None:
        try:
            if self._dialog is not None:
                self._dialog.endExecute()
        except Exception:
            log.exception("endExecute failed")

    def _on_cancel(self) -> None:
        log.info("user clicked Cancel; server-side job %s keeps running", self.job_id)
        self.cancelled = True
        self._end_dialog()

    # --- Layout helpers ---

    def _add(self, container, service_name: str, name: str,
             x: int, y: int, w: int, h: int):
        ctrl = container.createInstance(service_name)
        ctrl.PositionX = x
        ctrl.PositionY = y
        ctrl.Width = w
        ctrl.Height = h
        ctrl.Name = name
        container.insertByName(name, ctrl)
        return ctrl

    def _add_label(self, container, name: str, x: int, y: int, w: int, h: int,
                   text: str):
        c = self._add(container, "com.sun.star.awt.UnoControlFixedTextModel",
                      name, x, y, w, h)
        c.Label = text
        return c

    def _dialog_status_multiline(self, model) -> None:
        """Make the "status" label multi-line so longer messages wrap."""
        # The fixed-text model has a MultiLine property in newer LO; on older
        # versions it just no-ops harmlessly.
        try:
            model.getByName("status").MultiLine = True
        except Exception:
            pass


# --- Result dialog: multi-line read-only text -----------------------------

def show_text_result(ctx, title: str, body: str,
                     extra_button: tuple[str, "callable"] | None = None) -> None:
    """Show a multi-line text area inside a dismissible dialog.

    ``extra_button`` is an optional ``(label, callable)`` -- the callable is
    invoked when that button is clicked (used by /transcribe to add a "Grade
    this essay" button that kicks off /jobs/grade).
    """
    smgr = _smgr(ctx)
    model = smgr.createInstanceWithContext(
        "com.sun.star.awt.UnoControlDialogModel", ctx
    )
    model.Width = 520
    model.Height = 360
    model.Title = title

    text_ctrl_model = model.createInstance(
        "com.sun.star.awt.UnoControlEditModel"
    )
    text_ctrl_model.PositionX = 6
    text_ctrl_model.PositionY = 6
    text_ctrl_model.Width = 508
    text_ctrl_model.Height = 320
    text_ctrl_model.Name = "txt"
    text_ctrl_model.MultiLine = True
    text_ctrl_model.VScroll = True
    text_ctrl_model.ReadOnly = True
    text_ctrl_model.Text = body
    model.insertByName("txt", text_ctrl_model)

    if extra_button is not None:
        btn_extra = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
        btn_extra.PositionX = 6
        btn_extra.PositionY = 332
        btn_extra.Width = 140
        btn_extra.Height = 22
        btn_extra.Name = "btn_extra"
        btn_extra.Label = extra_button[0]
        btn_extra.PushButtonType = 0  # standard -- listener decides on dismissal
        model.insertByName("btn_extra", btn_extra)

    btn = model.createInstance("com.sun.star.awt.UnoControlButtonModel")
    btn.PositionX = 454
    btn.PositionY = 332
    btn.Width = 60
    btn.Height = 22
    btn.Name = "btn_close"
    btn.Label = "Close"
    btn.PushButtonType = 1  # OK
    btn.DefaultButton = True
    model.insertByName("btn_close", btn)

    dlg = smgr.createInstanceWithContext("com.sun.star.awt.UnoControlDialog", ctx)
    dlg.setModel(model)
    dlg.createPeer(_toolkit(ctx), None)

    if extra_button is not None:
        # Capture the callable + a closing reference to dlg for the listener.
        cb = extra_button[1]
        def _on_extra(_ev):
            try:
                dlg.endExecute()
            finally:
                # Run the callback AFTER dismissing the result dialog so the
                # next dialog (grade progress) doesn't stack on top.
                cb()
        dlg.getControl("btn_extra").addActionListener(_FnActionListener(_on_extra))

    dlg.execute()
    dlg.dispose()


# --- File picker helper ---------------------------------------------------

def _pick_image(ctx, title: str) -> str | None:
    """Open a single-file FilePicker for image selection. Returns system path
    or None if the user cancelled."""
    fp = _create(ctx, "com.sun.star.ui.dialogs.FilePicker")
    fp.setTitle(title)
    fp.appendFilter("Images", "*.jpg;*.jpeg;*.png;*.bmp;*.tif;*.tiff;*.webp")
    fp.appendFilter("All files", "*.*")
    if not fp.execute():
        return None
    file_urls = tuple(fp.getFiles() or ())
    if not file_urls:
        return None
    return uno.fileUrlToSystemPath(file_urls[0])


# --- AWT listener glue ----------------------------------------------------

class _FnActionListener(unohelper.Base, XActionListener):
    """Adapt a Python callable to com.sun.star.awt.XActionListener.

    Must inherit from ``unohelper.Base`` AND the actual UNO interface so that
    UNO's ``getTypes()`` introspection works -- duck-typed objects raise
    'Couldn't convert ... to a UNO type; AttributeError: getTypes'.
    """

    def __init__(self, fn):
        self._fn = fn

    def actionPerformed(self, event):
        self._fn(event)

    def disposing(self, event):
        pass


class _FnPropertyListener(unohelper.Base, XPropertyChangeListener):
    def __init__(self, fn):
        self._fn = fn

    def propertyChange(self, event):
        self._fn(event)

    def disposing(self, event):
        pass
