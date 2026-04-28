import os
import requests
import tiktoken
from retry import retry
from openai import OpenAI

from .logger import Logger

def shorten_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """
    Only keep the latest LLM output and correction feedback
    """
    Logger.log(f"Shortening messages from: {[m['role'] for m in messages]}", subsection=False)
    if len(messages) == 1:
        return [messages[0]]
    else:
        short_message = [messages[0]] + messages[-2:]
        assert short_message[1]['role'] == 'assistant'
        assert short_message[2]['role'] == 'user'
        return short_message

class LLM_Chat:
    # Simple base class for the LLM chat
    def __init__(self, *args, **kwargs):
        self.in_tokens = 0
        self.out_tokens = 0

    def get_response(self, prompt=None, messages=None):
        raise NotImplementedError

    def token_usage(self) -> tuple[int, int]:
        return self.in_tokens, self.out_tokens

    def reset_token_usage(self):
        self.in_tokens = 0
        self.out_tokens = 0

    def log_in_out(self, messages, llm_output):
        Logger.log("Messages to sends:", subsection=False)
        for m in messages:
            Logger.log(f"----- {m['role']} -----\n{m['content']}", subsection=False)
        Logger.print("LLM output:\n", llm_output)

class GPT_Chat(LLM_Chat):
    def __init__(self, engine, stop=None, temperature=0, top_p=1e-4,
                 frequency_penalty=0.0, presence_penalty=0.0, seed=0):
        super().__init__()
        engine = engine.strip().lower()
        self.engine = engine
        self.temperature = temperature
        self.top_p = top_p
        self.freq_penalty = frequency_penalty
        self.presence_penalty = presence_penalty
        self.stop = stop
        context_lengths = {
            "gpt-3.5-turbo-0125": 16e3, # 16k tokens
            "gpt-3.5-turbo-instruct": 4e3, # 4k tokens
            "gpt-4-1106-preview": 128e3, # 128k tokens
            "gpt-4-turbo": 128e3, # 128k tokens
            "gpt-4": 8192, # ~8k tokens
            "gpt-4-32k": 32768, # ~32k tokens
            "gpt-4o": 128e3, # ~32k tokens
            "gpt-4o-mini": 128e3, # 128k tokens
            "gpt-4o-2024-08-06": 128e3, # 128k tokens
            "o3-mini": 128e3, # 128k tokens
        }
        self.context_length = context_lengths.get(engine, 32e3) # 32k tokens is hopefully enough for most domains, and is supported by most models. In particular by the newer ones.
        if engine not in context_lengths:
            Logger.print(f"WARNING: Context length for {engine} is not specified. Using 32k tokens as default. You can add it in {__file__}")
        if "OPENAI_API_KEY" not in os.environ:
            Logger.print("WARNING: OPENAI_API_KEY is not set. Either export it as an environmental variable or if using Docker, add it to '.env'.")
            raise ValueError("OPENAI_API_KEY is not set. Either export it as an environmental variable or, if using Docker, add it to '.env'.")
        self.client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY', None))
        max_tokens = {
            "gpt-3.5-turbo-0125": 4e3, # 4k tokens
            "gpt-3.5-turbo-instruct": 4e3, # 4k tokens
            "gpt-4-1106-preview": 4e3, # 4k tokens
            "gpt-4-turbo": 4e3, # 4k tokens
            "gpt-4": 8e3, # 8k tokens
            "gpt-4-32k": 8e3, # 8k tokens
            "gpt-4o": 16e3, # 8k tokens
            "gpt-4o-mini": 16e3, # 4k tokens
            "gpt-4o-2024-08-06": 16e3, # 4k tokens
            "o3-mini": 16e3, # 16k tokens
        }
        self.max_tokens = max_tokens.get(engine, 4e3) # 4k tokens should be enough for most domains, and is supported by all models
        if engine not in max_tokens:
            Logger.print(f"WARNING: Max tokens for {engine} is not specified. Using 4k tokens as default. You can add it in {__file__}")
        self.tok = tiktoken.encoding_for_model(engine)
        self.in_tokens = 0
        self.out_tokens = 0
        self.seed = seed

    #@retry(tries=2, delay=60)
    def connect_openai(self, engine, messages, temperature, max_tokens, top_p, seed):
        kwargs = {
            "model": engine,
            "messages": messages,
        }
        if engine == "o3-mini":
            kwargs["reasoning_effort"] = "medium"
        else:
            kwargs["max_tokens"] = max_tokens
            kwargs["temperature"] = temperature
            kwargs["top_p"] = top_p
            kwargs["seed"] = seed
        
        return self.client.chat.completions.create(
            **kwargs
        )

    def get_response(self, prompt=None, messages=None, end_when_error=False, max_retry=5, est_margin = 200):
        if prompt is None and messages is None:
            raise ValueError("prompt and messages cannot both be None")
        if messages is not None:
            messages = messages
        else:
            messages = [{'role': 'user', 'content': prompt}]

        # Calculate the number of tokens to request. At most self.max_tokens, and prompt + request < self.context_length
        current_tokens = int(sum([len(self.tok.encode(m['content'])) for m in messages])) # Estimate current usage
        requested_tokens = int(min(self.max_tokens, self.context_length - current_tokens - est_margin)) # Request with safety margin
        Logger.log(f"Requesting {requested_tokens} tokens from {self.engine} (estimated {current_tokens - est_margin} prompt tokens with a safety margin of {est_margin} tokens)")
        self.in_tokens += current_tokens

        # Request the response
        n_retry = 0
        conn_success = False
        while not conn_success:
            n_retry += 1
            if n_retry >= max_retry:
                break
            try:
                print(f'[INFO] connecting to the LLM ({requested_tokens} tokens)...')
                response = self.connect_openai(
                    engine=self.engine,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=requested_tokens,
                    top_p=self.top_p,
                    seed=self.seed,
                )
                llm_output = response.choices[0].message.content # response['choices'][0]['message']['content']
                fingerprint = response.system_fingerprint
                conn_success = True
            except Exception as e:
                print(f'[ERROR] LLM error: {e}')
                if end_when_error:
                    break
        if not conn_success:
            raise ConnectionError(f'Failed to connect to the LLM after {max_retry} retries. Likely this is due to an invalid API key, please double-check the key and try again. If the problem persists, it may be due to a server-side issue. If so, please try again later. If the problem persists, please contact the developers.')

        response_tokens = len(self.tok.encode(llm_output)) # Estimate response tokens
        self.out_tokens += response_tokens

        self.log_in_out(messages, llm_output)
        Logger.log(f"The above message was generated by {self.engine} with seed {self.seed}. The resulting fingerprint was: {fingerprint}.")

        return llm_output

class OLLAMA_Chat(LLM_Chat):
    def __init__(self, engine, stop=None, max_tokens=8e3, temperature=0, top_p=1,
                 frequency_penalty=0.0, presence_penalty=0.0, seed=0, num_ctx=8192, num_batch=1024):
        super().__init__()
        print("WARNING: Ollama LLM usage is largely untested and may not work as expected.")
        self.engine = engine
        self.url = os.environ.get("OLLAMA_URL", ).strip("/").replace("api/generate", "api/chat")
        if not self.url.endswith("/"):
            self.url += "/"
        if not self.url.endswith("api/chat/"):
            self.url += "api/chat/"
        self.temperature = temperature
        self.seed = seed
        self.top_p = top_p
        self.presence_penalty = presence_penalty
        self.frequency_penalty = frequency_penalty
        self.in_tokens = 0
        self.out_tokens = 0
        self.tok = tiktoken.get_encoding("o200k_base") # For gpt:oss
        self.num_ctx = num_ctx
        self.num_batch = num_batch

    def get_response(self, prompt=None, messages=None):
        if prompt is None and messages is None:
            raise ValueError("prompt and messages cannot both be None")
        if messages is not None:
            messages = messages
        else:
            messages = [{'role': 'user', 'content': prompt}]

        self.in_tokens += sum([len(self.tok.encode(m['content'])) for m in messages])

        to_send = {
            "model": self.engine,
            "messages": messages,
            "stream": False,
            "options": {
                "seed": self.seed,
                "temperature": self.temperature,
                "top_p": self.top_p,
                "presence_penalty": self.presence_penalty,
                "frequency_penalty": self.frequency_penalty,
                "num_ctx": self.num_ctx,
                "num_batch": self.num_batch,
            }
        }

        resp = requests.post(self.url, json=to_send)
        if resp.status_code != 200:
            print(f"Failed to connect to OLLAMA at {self.url}: {resp.status_code}. \n\t{resp.text}")
            raise ConnectionError(f"Failed to connect to OLLAMA at {self.url}: {resp.status_code}. \n\t{resp.text}")
        output = resp.json()["message"]["content"]

        self.out_tokens += len(self.tok.encode(output))

        self.log_in_out(messages, output)
        return output

    def token_usage(self) -> tuple[int, int]:
        print("WARNING: Ollama token usage is currently estimated with GPT tokenization.")
        return self.in_tokens, self.out_tokens

class LOCAL_LLAMA_Chat(LLM_Chat):
    def __init__(self, engine, stop=None, max_tokens=8e3, temperature=0, top_p=1,
                 frequency_penalty=0.0, presence_penalty=0.0, seed=0):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, set_seed

        model_id = "meta-llama/Meta-Llama-3.1-70B-Instruct"
        access_token = os.environ.get("HF_TOKEN", None)
        if access_token is None:
            print("WARNING: `HF_TOKEN` environment variable is not specified. Local LLAMA model might fail.")
        if os.environ.get("HF_HOME", None) is None:
            print("WARNING: `HF_HOME` environment variable is not specified. Local LLAMA model will be placed at the default location.")

        quantization_config = BitsAndBytesConfig(
            load_in_4bit = "4bit" in engine,
            load_in_8bit = "8bit" in engine,
        )
        self._set_seed = set_seed
        self.quantized_model = AutoModelForCausalLM.from_pretrained(
            model_id, torch_dtype=torch.bfloat16, quantization_config=quantization_config,
            token=access_token, device_map="auto"
        )

        self.tokenizer = AutoTokenizer.from_pretrained(model_id)

        self.max_tokens = max_tokens
        self.temperature = temperature
        if self.temperature == 0:
            self.temperature = 1e-10 # LLAMA 3.1 does not support temperature 0
        self.top_p = top_p
        self.seed = seed
        self.in_tokens = 0
        self.out_tokens = 0

    def get_response(self, prompt=None, messages=None):
        self._set_seed(self.seed)

        if prompt is None and messages is None:
            raise ValueError("prompt and messages cannot both be None")
        if messages is not None:
            messages = messages
        else:
            messages = [{'role': 'user', 'content': prompt}]

        input_text = self.messages_to_text(messages)
        input_tokens = self.tokenizer(input_text, return_tensors="pt").to("cuda")
        num_in_tokens = len(input_tokens[0])
        self.in_tokens += num_in_tokens

        output_tokens = self.quantized_model.generate(**input_tokens, max_new_tokens=self.max_tokens, temperature=self.temperature, top_p=self.top_p)
        output_tokens = output_tokens[0][num_in_tokens:]
        self.out_tokens += len(output_tokens)

        output = self.tokenizer.decode(output_tokens, skip_special_tokens=True)
        output = output.replace("?", " ?") # LLAMA 3.1 appears to be unable to generate " ?" and instead generates "?". As this is often used in PDDL, we compensate.

        self.log_in_out(messages, output)

        return output

    def messages_to_text(self, messages):
        text = "<|begin_of_text|>"
        for message in messages:
            text += f"<|start_header_id|>{message['role']}<|end_header_id|>\n\n"
            text += message["content"]
        text += "<|eot_id|>\n"
        text += "<|start_header_id|>assistant<|end_header_id|>"
        return text

def get_llm(engine, **kwargs) -> LLM_Chat:
    return OLLAMA_Chat(engine, **kwargs)
