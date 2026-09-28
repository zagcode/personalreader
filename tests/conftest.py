import os
import tempfile

# Antes de qualquer import de app.*: config lê o ambiente na importação.
os.environ["TTS_ENGINE"] = "mock"
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="personalreader-test-")
