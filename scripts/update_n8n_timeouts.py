import sys
import psycopg2
import json

db_uri = "postgresql://admin:password_super_segura_123@localhost:5432/evolution_db"

def main():
    try:
        conn = psycopg2.connect(db_uri)
        cursor = conn.cursor()
        print("Conectado ao banco de dados com sucesso!")

        # Buscar o workflow pelo ID
        cursor.execute("SELECT id, name, nodes FROM workflow_entity WHERE id = %s;", ('Yf3OwySpuR8OMDV4',))
        row = cursor.fetchone()
        if not row:
            print("Erro: Workflow 'Yf3OwySpuR8OMDV4' não encontrado!")
            return

        w_id, w_name, w_nodes = row
        if isinstance(w_nodes, str):
            nodes = json.loads(w_nodes)
        else:
            nodes = w_nodes

        updated = False
        for node in nodes:
            node_name = node.get("name", "")
            node_type = node.get("type", "")
            
            # Se for do tipo HTTP Request, atualizar o timeout
            if "httpRequest" in node_type or node_type == "n8n-nodes-base.httpRequest":
                params = node.get("parameters", {})
                options = params.get("options", {})
                
                old_timeout = options.get("timeout")
                if old_timeout != 30000:
                    options["timeout"] = 30000
                    params["options"] = options
                    node["parameters"] = params
                    print(f"  Atualizado timeout do nó '{node_name}' ({node_type}): {old_timeout} -> 30000")
                    updated = True

        if updated:
            nodes_json = json.dumps(nodes)
            cursor.execute("UPDATE workflow_entity SET nodes = %s WHERE id = %s;", (nodes_json, w_id))
            conn.commit()
            print("Workflow atualizado com sucesso no banco de dados!")
        else:
            print("Nenhum nó precisou de alteração de timeout.")

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Erro: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
