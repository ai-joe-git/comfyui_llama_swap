import re
import base64
import requests
import numpy as np
from io import BytesIO
from PIL import Image

DEFAULT_URL = "http://localhost:8080"

MAX_SEED = 0xFFFFFFFF
THINKING_MODES = ["auto", "on", "off"]


def _extract_thinking(text: str) -> tuple[str, str]:
    pattern = re.compile(r"<think(?:ing)?>(.*?)</think(?:ing)?>", re.DOTALL | re.IGNORECASE)
    thinking_parts = pattern.findall(text)
    thinking_text = "\n\n".join(p.strip() for p in thinking_parts)
    clean_text = pattern.sub("", text).strip()
    return clean_text, thinking_text


def _tensor_to_base64(image_tensor) -> str:
    img_np = (image_tensor.numpy() * 255).clip(0, 255).astype(np.uint8)
    pil_img = Image.fromarray(img_np, mode="RGB")
    buf = BytesIO()
    pil_img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


class LlamaSwapClient:
    CATEGORY = "llama-swap"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("response", "thinking")
    OUTPUT_TOOLTIPS = (
        "Clean response text with <think> blocks removed",
        "Extracted thinking/reasoning content (empty if model produced none)",
    )
    FUNCTION = "generate"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "server_url": ("STRING", {
                    "default": DEFAULT_URL,
                    "tooltip": "llama-swap server base URL",
                }),
                "model": ("STRING", {
                    "default": "",
                    "tooltip": "Model name — click Fetch Models button to pick from the server",
                }),
                "system_prompt": ("STRING", {
                    "default": "You are a helpful assistant.",
                    "multiline": True,
                    "tooltip": "System prompt sent before the user message",
                }),
                "prompt": ("STRING", {
                    "default": "Hello!",
                    "multiline": True,
                    "tooltip": "User message / question",
                }),
                "unload_after_generate": ("BOOLEAN", {
                    "default": False,
                    "label_on":  "Unload model after ✓",
                    "label_off": "Keep model loaded",
                    "tooltip": "Call /unload on the llama-swap server after generation",
                }),
                "seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": MAX_SEED,
                    "control_after_generate": True,
                    "tooltip": "Sampling seed. 0 leaves the seed out of the request so llama-swap picks one; any other value reproduces the same output",
                }),
                "thinking": (THINKING_MODES, {
                    "default": "auto",
                    "tooltip": "auto: leave it to the model/template. on/off: ask the template to enable or skip thinking (Qwen3-style templates)",
                }),
            },
            "optional": {
                "image": ("IMAGE", {
                    "tooltip": "Optional image for vision models (first frame used)",
                }),
            },
        }

    def generate(self, server_url, model, system_prompt, prompt, unload_after_generate,
                 seed=0, thinking="auto", image=None):
        base_url = server_url.rstrip("/")
        messages = []

        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt.strip()})

        if image is not None:
            img_b64 = _tensor_to_base64(image[0])
            user_content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            ]
        else:
            user_content = prompt

        messages.append({"role": "user", "content": user_content})

        payload = {"model": model, "messages": messages, "stream": False}

        if int(seed) > 0:
            payload["seed"] = int(seed)

        if thinking != "auto":
            payload["chat_template_kwargs"] = {"enable_thinking": thinking == "on"}

        try:
            r = requests.post(
                f"{base_url}/v1/chat/completions",
                json=payload,
                timeout=300,
            )
            r.raise_for_status()
            full_text = r.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            err = f"[LlamaSwap ERROR] {exc}"
            if unload_after_generate:
                try: requests.get(f"{base_url}/unload", timeout=5)
                except Exception: pass
            return (err, "")

        clean_text, thinking_text = _extract_thinking(full_text)

        if unload_after_generate:
            try: requests.get(f"{base_url}/unload", timeout=5)
            except Exception: pass

        return (clean_text, thinking_text)


class LlamaSwapModelSelector:
    CATEGORY = "llama-swap"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("model_name",)
    FUNCTION = "select"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "server_url": ("STRING", {"default": DEFAULT_URL}),
                "model": ("STRING", {
                    "default": "",
                    "tooltip": "Model name — click Fetch Models button to pick from the server",
                }),
            }
        }

    def select(self, server_url: str, model: str):
        return (model,)


NODE_CLASS_MAPPINGS = {
    "LlamaSwapClient":        LlamaSwapClient,
    "LlamaSwapModelSelector": LlamaSwapModelSelector,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LlamaSwapClient":        "🦙 Llama-Swap Client",
    "LlamaSwapModelSelector": "🦙 Llama-Swap Model Selector",
}
