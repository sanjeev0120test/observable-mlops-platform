"""
UC2 — LSTM Autoencoder for log anomaly detection.
Architecture:
  - Input: sequence of log event embeddings (TF-IDF + word count features)
  - Encoder: 2-layer LSTM → latent vector
  - Decoder: 2-layer LSTM → reconstruction
  - Anomaly score: reconstruction MSE loss
  - Threshold: 95th percentile of normal training loss

Training on 'normal' (no-burst) log windows,
tested on injected error burst windows from generate_container_logs.py.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

logger = logging.getLogger(__name__)

WINDOW_SIZE = 50  # log lines per window
EMBEDDING_DIM = 20  # TF-IDF feature dimension
HIDDEN_DIM = 32
NUM_LAYERS = 2
LATENT_DIM = 16
EPOCHS = 10
BATCH_SIZE = 64
LEARNING_RATE = 1e-3


class LSTMAutoencoder(nn.Module):
    def __init__(
        self,
        input_dim: int = EMBEDDING_DIM,
        hidden_dim: int = HIDDEN_DIM,
        latent_dim: int = LATENT_DIM,
        num_layers: int = NUM_LAYERS,
    ) -> None:
        super().__init__()
        self.encoder = nn.LSTM(input_dim, hidden_dim, num_layers, batch_first=True)
        self.enc_to_latent = nn.Linear(hidden_dim, latent_dim)
        self.latent_to_dec = nn.Linear(latent_dim, hidden_dim)
        self.decoder = nn.LSTM(hidden_dim, input_dim, num_layers, batch_first=True)

    def encode(self, x: torch.Tensor) -> tuple[torch.Tensor, tuple]:
        out, (h, c) = self.encoder(x)
        latent = self.enc_to_latent(out[:, -1, :])
        return latent, (h, c)

    def decode(self, latent: torch.Tensor, seq_len: int) -> torch.Tensor:
        dec_input = self.latent_to_dec(latent).unsqueeze(1).repeat(1, seq_len, 1)
        out, _ = self.decoder(dec_input)
        return out

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        latent, _ = self.encode(x)
        return self.decode(latent, x.shape[1])


def _extract_features(log_lines: list[str]) -> np.ndarray:
    """
    Extract TF-IDF-like features from log lines.
    Returns (n_windows, WINDOW_SIZE, EMBEDDING_DIM) array.
    """
    from sklearn.feature_extraction.text import HashingVectorizer

    vectorizer = HashingVectorizer(
        n_features=EMBEDDING_DIM, norm="l2", alternate_sign=False
    )

    windows = []
    for i in range(0, len(log_lines) - WINDOW_SIZE + 1, WINDOW_SIZE // 2):
        window = log_lines[i : i + WINDOW_SIZE]
        if len(window) < WINDOW_SIZE:
            break
        features = vectorizer.transform(window).toarray().astype(np.float32)
        windows.append(features)

    return np.array(windows)  # (n_windows, WINDOW_SIZE, EMBEDDING_DIM)


def train(
    normal_logs: list[str],
    model_path: Path = Path("mlops/experiments/log_anomaly/lstm_ae.pt"),
    epochs: int = EPOCHS,
    device: str = "cpu",
) -> tuple[LSTMAutoencoder, float]:
    """
    Train LSTM autoencoder on normal log windows.
    Returns (model, threshold) where threshold = 95th percentile of training losses.
    """
    X = _extract_features(normal_logs)
    if len(X) == 0:
        raise ValueError("Not enough log lines to form windows. Need at least WINDOW_SIZE lines.")

    tensor = torch.tensor(X, dtype=torch.float32)
    dataset = TensorDataset(tensor)
    loader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True)

    model = LSTMAutoencoder()
    model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.MSELoss()

    for epoch in range(epochs):
        model.train()
        total_loss = 0.0
        for (batch,) in loader:
            batch = batch.to(device)
            recon = model(batch)
            loss = criterion(recon, batch)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total_loss += loss.item()
        avg = total_loss / len(loader)
        if epoch % 2 == 0:
            logger.info("Epoch %d/%d  loss=%.6f", epoch + 1, epochs, avg)

    # Compute threshold on training data
    model.eval()
    all_losses: list[float] = []
    with torch.no_grad():
        for (batch,) in loader:
            batch = batch.to(device)
            recon = model(batch)
            losses = ((recon - batch) ** 2).mean(dim=(1, 2))
            all_losses.extend(losses.cpu().numpy().tolist())

    threshold = float(np.percentile(all_losses, 95))
    logger.info("Training complete. Anomaly threshold (p95): %.6f", threshold)

    model_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"model_state": model.state_dict(), "threshold": threshold}, str(model_path))
    logger.info("Model saved to %s", model_path)

    return model, threshold


def evaluate(
    model: LSTMAutoencoder,
    threshold: float,
    test_logs: list[str],
    labels: list[bool] | None = None,
    device: str = "cpu",
) -> dict:
    """
    Evaluate model on test log windows.
    Returns precision@10, recall@10, and reconstruction_loss_threshold.
    """
    X = _extract_features(test_logs)
    if len(X) == 0:
        return {"error": "no windows extracted from test logs"}

    tensor = torch.tensor(X, dtype=torch.float32)
    model.eval()
    with torch.no_grad():
        recon = model(tensor.to(device))
        losses = ((recon - tensor.to(device)) ** 2).mean(dim=(1, 2)).cpu().numpy()

    scores = losses.tolist()
    predicted_anomaly = [s > threshold for s in scores]

    if labels is None:
        return {
            "n_windows": len(scores),
            "n_anomalies_predicted": sum(predicted_anomaly),
            "threshold": threshold,
            "reconstruction_loss_threshold": float(np.percentile(scores, 95)),
        }

    # Compute precision@10 and recall@10
    ranked_idx = np.argsort(scores)[::-1][:10]
    if len(labels) < len(scores):
        labels = labels + [False] * (len(scores) - len(labels))

    tp_at_10 = sum(labels[i] for i in ranked_idx)
    total_positives = sum(labels[: len(scores)])

    precision_at_10 = tp_at_10 / min(10, len(ranked_idx))
    recall_at_10 = tp_at_10 / max(total_positives, 1)

    return {
        "n_windows": len(scores),
        "n_anomalies_predicted": sum(predicted_anomaly),
        "anomaly_precision_at_10": round(precision_at_10, 4),
        "anomaly_recall_at_10": round(recall_at_10, 4),
        "reconstruction_loss_threshold": round(float(np.percentile(scores, 95)), 6),
        "threshold": threshold,
    }
