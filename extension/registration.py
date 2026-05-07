"""LibreOffice extension entry point.

Registers ``org.aitutor.AIEssayTutor`` as an XJobExecutor. The Addons.xcu
toolbar button URL ``service:org.aitutor.AIEssayTutor?transcribe`` invokes
``trigger("transcribe")`` on this component, which delegates to the
orchestration code in ``pythonpath/aitutor/handler.py``.

This file MUST live at the extension root (referenced from
META-INF/manifest.xml) and is loaded once per LibreOffice process.
"""
import sys
import traceback

import uno
import unohelper
from com.sun.star.task import XJobExecutor


class AITutorJob(unohelper.Base, XJobExecutor):
    """Single dispatch point. The toolbar URL's query string (``?transcribe``)
    is passed to ``trigger`` as the argument."""

    def __init__(self, ctx):
        self.ctx = ctx

    def trigger(self, arg):
        try:
            # Lazy import so any error inside the handler shows a friendly dialog
            # instead of preventing component registration at LO startup.
            from aitutor import handler

            if arg == "transcribe":
                handler.run_transcribe(self.ctx)
            else:
                handler.show_error(self.ctx, f"Unknown command: {arg}")
        except Exception:
            tb = traceback.format_exc()
            try:
                from aitutor import handler
                handler.show_error(self.ctx, f"Internal error:\n{tb}")
            except Exception:
                # If even the error path fails, fall back to stderr (visible in
                # console builds of LO; otherwise just lost).
                sys.stderr.write(tb)


# UNO component registration -- this `g_ImplementationHelper` symbol is what
# LibreOffice looks for when it loads the .py UNO component.
g_ImplementationHelper = unohelper.ImplementationHelper()
g_ImplementationHelper.addImplementation(
    AITutorJob,
    "org.aitutor.AIEssayTutor",
    ("com.sun.star.task.JobExecutor",),
)
