__version__ = "0.1.0"

# --- PaddlePaddle compatibility flags --------------------------------------
# paddlepaddle 3.x ships a new PIR (PaddleIR) executor that does not handle
# every attribute type used by some PP-OCRv5 ops; loading PaddleOCR can fail
# with "ConvertPirAttribute2RuntimeAttribute not support
# [pir::ArrayAttribute<pir::DoubleAttribute>]". Disable PIR + oneDNN by every
# flag name we know paddle has used across recent releases. These MUST be set
# before paddle is first imported, hence why they live in this top-level
# package init (which runs before any submodule).
#
# The PaddleOCR constructor's ``enable_mkldnn=False`` param is also passed at
# the call sites (pipeline.py / manager.py) as a belt-and-suspenders measure.
import os
for _k in (
    "FLAGS_enable_pir_in_executor",
    "FLAGS_enable_new_ir_in_executor",
    "FLAGS_use_mkldnn",
    "FLAGS_use_onednn",
):
    os.environ.setdefault(_k, "0")
del os, _k
