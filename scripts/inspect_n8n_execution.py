import sys
import psycopg2
import json

db_uri = "postgresql://admin:password_super_segura_123@localhost:5432/evolution_db"

def main():
    try:
        conn = psycopg2.connect(db_uri)
        cursor = conn.cursor()
        print("Conectado ao banco de dados com sucesso!")

        # Buscar as últimas execuções
        cursor.execute("""
            SELECT id, status, "startedAt", "stoppedAt" 
            FROM execution_entity 
            WHERE "workflowId" = %s
            ORDER BY "startedAt" DESC 
            LIMIT 10;
        """, ('Yf3OwySpuR8OMDV4',))
        
        rows = cursor.fetchall()
        if not rows:
            print("Nenhuma execução encontrada!")
            return
            
        print("Últimas 10 execuções:")
        for idx, row in enumerate(rows):
            exec_id, status, started, stopped = row
            print(f"  {idx}: ID={exec_id}, status={status}, started={started}")

        # Perguntar qual analisar (usaremos a primeira que deu erro)
        exec_id = None
        for row in rows:
            if row[1] == 'error':
                exec_id = row[0]
                break
                
        if not exec_id:
            print("Nenhuma execução com erro encontrada nas últimas 10!")
            return
            
        print(f"\nAnalisando execução com erro: ID {exec_id}")

        # Buscar dados de execução na tabela execution_data
        cursor.execute("""
            SELECT data 
            FROM execution_data 
            WHERE "executionId" = %s;
        """, (exec_id,))
        
        data_row = cursor.fetchone()
        if not data_row:
            print(f"Nenhum dado encontrado na tabela execution_data para execução {exec_id}!")
            return
            
        exec_data_raw = data_row[0]
        if isinstance(exec_data_raw, str):
            exec_data = json.loads(exec_data_raw)
        else:
            exec_data = exec_data_raw

        print(f"Tipo do dado carregado: {type(exec_data)}")
        if isinstance(exec_data, list):
            print(f"Comprimento da lista: {len(exec_data)}")
            for idx in range(14, 24):
                if idx < len(exec_data):
                    item = exec_data[idx]
                    print(f"\nItem {idx}: type={type(item)}")
                    try:
                        print(json.dumps(item, indent=2))
                    except Exception:
                        print(item)
        else:
            print("Não é uma lista.")

        cursor.close()
        conn.close()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
