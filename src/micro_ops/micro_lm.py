"""Tiny character-level language model and local training helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

try:
    import torch
    from torch import nn
except ImportError:  # Keep the core desktop app usable without the optional ML package.
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]


STARTER_CORPUS = """school project schedule
track each project task
check supplies before work
report low stock early
finish preparation before delivery
update task status when work changes
plan the science fair display
review inventory and schedule
"""


if nn is not None:
    class MicroLanguageModel(nn.Module):
        """Small GRU language model; parameter count is deliberately above 1,000."""

        def __init__(self, vocabulary_size: int, embedding_size: int = 32, hidden_size: int = 48) -> None:
            super().__init__()
            self.embedding = nn.Embedding(vocabulary_size, embedding_size)
            self.recurrent = nn.GRU(embedding_size, hidden_size, batch_first=True)
            self.output = nn.Linear(hidden_size, vocabulary_size)

        def forward(self, tokens: torch.Tensor) -> torch.Tensor:
            embedded = self.embedding(tokens)
            outputs, _ = self.recurrent(embedded)
            return self.output(outputs)
else:
    class MicroLanguageModel:  # type: ignore[no-redef]
        def __init__(self, *_: object, **__: object) -> None:
            raise ImportError("Install PyTorch to train or use the MicroLM.")


def train_model(
    corpus: str,
    output_path: str | Path,
    epochs: int = 80,
    progress: Callable[[int, int, float], None] | None = None,
) -> dict[str, object]:
    if torch is None:
        raise ImportError("PyTorch is required for training. Install it from pytorch.org, then restart MicroOps.")
    text = "\n".join(line.strip() for line in corpus.splitlines() if line.strip())
    if len(text) < 40:
        raise ValueError("Add at least 40 characters of training text (a few short sentences).")
    if not 1 <= epochs <= 2000:
        raise ValueError("Training epochs must be from 1 to 2000.")
    vocabulary = sorted(set(text))
    if len(vocabulary) < 3:
        raise ValueError("Training text must contain at least three different characters.")
    char_to_id = {char: index for index, char in enumerate(vocabulary)}
    encoded = torch.tensor([char_to_id[char] for char in text], dtype=torch.long)
    sequence_length = min(48, max(8, len(text) // 8))
    examples = max(1, len(encoded) - sequence_length)
    starts = torch.arange(examples)
    model = MicroLanguageModel(len(vocabulary))
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.008)
    loss_function = nn.CrossEntropyLoss()
    losses: list[float] = []
    model.train()
    for epoch in range(1, epochs + 1):
        order = starts[torch.randperm(len(starts))]
        running_loss = 0.0
        batches = 0
        for offset in range(0, len(order), 32):
            batch_starts = order[offset : offset + 32]
            inputs = torch.stack([encoded[start : start + sequence_length] for start in batch_starts])
            targets = torch.stack([encoded[start + 1 : start + sequence_length + 1] for start in batch_starts])
            optimizer.zero_grad(set_to_none=True)
            logits = model(inputs)
            loss = loss_function(logits.reshape(-1, len(vocabulary)), targets.reshape(-1))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            running_loss += float(loss.detach())
            batches += 1
        average_loss = running_loss / max(1, batches)
        losses.append(average_loss)
        if progress and (epoch == 1 or epoch % max(1, epochs // 50) == 0 or epoch == epochs):
            progress(epoch, epochs, average_loss)
    parameter_count = sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state_dict": model.state_dict(),
        "vocabulary": vocabulary,
        "embedding_size": 32,
        "hidden_size": 48,
        "parameters": parameter_count,
        "epochs": epochs,
        "final_loss": losses[-1],
    }
    torch.save(payload, destination)
    return {key: value for key, value in payload.items() if key not in ("state_dict", "vocabulary")} | {"path": str(destination), "vocabulary_size": len(vocabulary)}


def generate_text(model_path: str | Path, prompt: str, new_characters: int = 120) -> str:
    if torch is None:
        raise ImportError("PyTorch is required for generation. Install it from pytorch.org, then restart MicroOps.")
    path = Path(model_path)
    if not path.exists():
        raise ValueError("Train the MicroLM first.")
    payload = torch.load(path, map_location="cpu", weights_only=True)
    vocabulary = payload["vocabulary"]
    char_to_id = {char: index for index, char in enumerate(vocabulary)}
    if not prompt:
        prompt = "school"
    tokens = [char_to_id.get(char, char_to_id.get(" ", 0)) for char in prompt]
    model = MicroLanguageModel(len(vocabulary), payload["embedding_size"], payload["hidden_size"])
    model.load_state_dict(payload["state_dict"])
    model.eval()
    generated = prompt
    with torch.no_grad():
        for _ in range(max(1, min(new_characters, 500))):
            logits = model(torch.tensor([tokens[-80:]], dtype=torch.long))[0, -1]
            probabilities = torch.softmax(logits / 0.85, dim=-1)
            next_id = int(torch.multinomial(probabilities, 1))
            tokens.append(next_id)
            generated += vocabulary[next_id]
    return generated
