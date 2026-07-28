import os
import time
import psycopg2
import json # Para lidar com a coluna JSONB 'items'
from dotenv import load_dotenv
from pathlib import Path
from uuid import UUID # Para converter order_id para UUID se necessário

# --- Configuração do ambiente ---
# Garante que o .env seja lido a partir da pasta do script
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL não foi carregada. "
        f"Verifique se o arquivo .env existe em: {env_path} "
        "e contém a variável DATABASE_URL."
    )

# --- Funções de processamento ---

def processar_pedido(cur, order_id: UUID, items: list):
    """
    Tenta debitar todos os itens do pedido dentro de um SAVEPOINT.
    Se qualquer item falhar (ex: falta de estoque), reverte apenas esse pedido.
    Retorna True se todos os itens foram debitados com sucesso, False caso contrário.
    """
    cur.execute("SAVEPOINT pedido_atual") # Cria um ponto de restauração para este pedido

    for item in items:
        sku = item.get("sku")
        quantity = item.get("quantity")

        if not sku or not isinstance(quantity, int) or quantity <= 0:
            print(f"  [ERRO] Item inválido no pedido {order_id}: {item}")
            cur.execute("ROLLBACK TO SAVEPOINT pedido_atual")
            return False

        try:
            # Chama a função debit_stock no banco de dados
            cur.execute(
                "SELECT debit_stock(%s, %s, %s)",
                (sku, quantity, order_id)
            )
            sucesso = cur.fetchone()[0] # A função retorna TRUE ou FALSE

            if not sucesso:
                print(f"  [INFO] Estoque insuficiente para SKU {sku} no pedido {order_id}.")
                cur.execute("ROLLBACK TO SAVEPOINT pedido_atual") # Reverte débitos parciais
                return False

        except psycopg2.Error as db_err:
            # Captura erros específicos do banco (ex: SKU não encontrado)
            print(f"  [ERRO DB] Falha ao debitar SKU {sku} para pedido {order_id}: {db_err}")
            cur.execute("ROLLBACK TO SAVEPOINT pedido_atual")
            return False
        except Exception as e:
            print(f"  [ERRO GERAL] Falha inesperada ao debitar SKU {sku} para pedido {order_id}: {e}")
            cur.execute("ROLLBACK TO SAVEPOINT pedido_atual")
            return False

    cur.execute("RELEASE SAVEPOINT pedido_atual") # Libera o ponto de restauração
    return True


def processar_pedidos_pendentes():
    """
    Conecta ao banco, busca pedidos com status 'created' e tenta processá-los.
    """
    conn = None
    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = False # Desabilita autocommit para gerenciar transações manualmente
        cur = conn.cursor()

        print(f"[{datetime.now().isoformat()}] Buscando pedidos pendentes...")

        # Busca pedidos com status 'created', ordenados por criação, limitando para não sobrecarregar
        # FOR UPDATE SKIP LOCKED evita que múltiplas instâncias do worker processem o mesmo pedido
        cur.execute("""
            SELECT order_id, items
            FROM orders
            WHERE status = 'created'
            ORDER BY created_at ASC
            LIMIT 20
            FOR UPDATE SKIP LOCKED
        """)

        pedidos = cur.fetchall()

        if not pedidos:
            print("Nenhum pedido pendente encontrado.")
            return

        print(f"Encontrados {len(pedidos)} pedidos pendentes.")

        for order_id_str, items_json in pedidos:
            order_id = UUID(order_id_str) # Converte a string para UUID
            items = json.loads(items_json) # Converte a string JSONB para lista/dict Python

            try:
                sucesso = processar_pedido(cur, order_id, items)
                novo_status = "confirmed" if sucesso else "rejected_no_stock"

                cur.execute(
                    "UPDATE orders SET status = %s WHERE order_id = %s",
                    (novo_status, order_id)
                )
                conn.commit() # Confirma a transação para este pedido
                print(f"  [STATUS] Pedido {order_id}: {novo_status}")

            except Exception as erro:
                conn.rollback() # Em caso de erro inesperado, desfaz tudo para este pedido
                print(f"  [ERRO CRÍTICO] Falha ao processar pedido {order_id}: {erro}. Rollback completo.")

        cur.close()

    except psycopg2.Error as db_err:
        print(f"[ERRO DB GERAL] Falha na conexão ou operação de banco: {db_err}")
        if conn:
            conn.rollback() # Garante rollback se a transação principal falhar
    except Exception as e:
        print(f"[ERRO GERAL] Falha inesperada no worker: {e}")
    finally:
        if conn:
            conn.close() # Garante que a conexão seja fechada


# --- Loop principal do worker ---
if __name__ == "__main__":
    print("Worker de processamento de pedidos iniciado.")
    while True:
        processar_pedidos_pendentes()
        time.sleep(5) # Espera 5 segundos antes de buscar novos pedidos