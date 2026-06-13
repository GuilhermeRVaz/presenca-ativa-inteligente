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
            print("Erro: Workflow 'Yf3OwySpuR8OMDV4' não encontrado no banco de dados!")
            return

        w_id, w_name, w_nodes = row
        print(f"Workflow encontrado: {w_name} ({w_id})")

        # nodes pode ser carregado como string JSON ou como dict diretamente dependendo do driver/banco
        if isinstance(w_nodes, str):
            nodes = json.loads(w_nodes)
        else:
            nodes = w_nodes

        print(f"Número de nós no workflow: {len(nodes)}")

        # Procurar por chaves sk-proj e substituí-las
        updated = False
        for node in nodes:
            node_name = node.get("name", "")
            # Procurar nas configurações de cabeçalhos
            params = node.get("parameters", {})
            headers = params.get("headerParameters", {}).get("parameters", [])
            for h in headers:
                if h.get("name") == "Authorization" and "sk-proj-" in str(h.get("value")):
                    print(f"  Encontrada chave sk-proj- no nó '{node_name}': {h.get('value')[:30]}...")
                    # Substituir pelo expression de ambiente do n8n
                    h["value"] = "=Bearer {{ $env.OPENAI_API_KEY }}"
                    updated = True

        if updated:
            # Salvar de volta no banco
            nodes_json = json.dumps(nodes)
            cursor.execute("UPDATE workflow_entity SET nodes = %s WHERE id = %s;", (nodes_json, w_id))
            conn.commit()
            print("Workflow atualizado com sucesso no banco de dados!")
        else:
            print("Nenhuma alteração necessária no workflow.")

        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Erro ao interagir com o banco de dados: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
