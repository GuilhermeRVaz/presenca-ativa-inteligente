import sys
import psycopg2
import json

db_uri = "postgresql://admin:password_super_segura_123@localhost:5432/evolution_db"

def main():
    try:
        conn = psycopg2.connect(db_uri)
        cursor = conn.cursor()
        print("Conectado ao banco de dados com sucesso!")

        # 1. Obter os nodes atualizados do workflow_entity
        cursor.execute("SELECT nodes, \"activeVersionId\" FROM workflow_entity WHERE id = %s;", ('Yf3OwySpuR8OMDV4',))
        row = cursor.fetchone()
        if not row:
            print("Erro: Workflow 'Yf3OwySpuR8OMDV4' não encontrado em workflow_entity!")
            return
            
        nodes, active_version_id = row
        if isinstance(nodes, str):
            nodes_json = nodes
        else:
            nodes_json = json.dumps(nodes)
            
        print(f"Workflow activeVersionId: {active_version_id}")
        
        # 2. Atualizar o workflow_history para essa versão
        cursor.execute("""
            UPDATE workflow_history 
            SET nodes = %s 
            WHERE "workflowId" = %s AND "versionId" = %s;
        """, (nodes_json, 'Yf3OwySpuR8OMDV4', active_version_id))
        
        updated_rows = cursor.rowcount
        conn.commit()
        print(f"workflow_history atualizado com sucesso! Linhas afetadas: {updated_rows}")

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Erro: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
