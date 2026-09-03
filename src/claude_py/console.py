import threading

from claude_py.config import PROMPT, READLINE_PROMPT, CLI_ACTIVE

try:
    import readline

    readline.parse_and_bind("set bind-tty-special-chars off")
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False


class ConsoleBroker:
    """Serialize normal prompts and worker permission questions on one stdin."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reader = None
        self.display_prompt = PROMPT
        self.readline_prompt = READLINE_PROMPT

    def set_prompt(self, display_prompt: str, readline_prompt: str):
        self.display_prompt = display_prompt
        self.readline_prompt = readline_prompt

    def ask(self, prompt: str | None = None) -> str:
        with self._lock:
            active_prompt = self.readline_prompt if prompt is None else prompt
            return (self.reader or input)(active_prompt)


CONSOLE = ConsoleBroker()


def terminal_print(text: str):
    if threading.current_thread() is threading.main_thread() or not CLI_ACTIVE:
        print(text)
        return
    line = ""
    if READLINE_AVAILABLE:
        try:
            line = readline.get_line_buffer()
        except Exception:
            line = ""
    print(f"\r\033[K{text}")
    print(CONSOLE.display_prompt + line, end="", flush=True)
