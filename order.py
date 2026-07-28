import os
import time
import uuid
import random

import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

API_URL = os.environ["API_URL"]
API_TOKEN = os.environ["API_TOKEN"]

produtos = [
    {"sku": "PROD-001", "preco": 29.90},
    {"sku": "PROD-002", "preco": 59.90},
    {"sku": "PROD-003", "preco": 99.90},
]

def criar_pedido():
    produto = random.choice(produtos)
    quantidade = random.randint(1, 3)

    return {
        "order_id": str(uuid.uuid4()),
        "customer_id": f"CUST-{random.randint(1, 1000):04d}",
        "items": [
            {
                "sku": produto["sku"],
                "quantity": quantidade,
                "unit_price": produto["preco"]
            }
        ],
        "total_amount": round(produto["preco"] * quantidade, 2),
        "created_at": datetime.now(timezone.utc).isoformat()
    }

def enviar_pedido(pedido):
    headers = {
        "apikey": API_TOKEN,
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"  # Tell Supabase to just insert without returning the data row
    }

    resposta = requests.post(API_URL, json=pedido, headers=headers, timeout=15)
    resposta.raise_for_status()
    return resposta


while True:
    pedido = criar_pedido()

    try:
        enviar_pedido(pedido)
        print(f"Pedido enviado: {pedido['order_id']}")
    except requests.RequestException as erro:
        print(f"Erro ao enviar pedido: {erro}")

    time.sleep(5)