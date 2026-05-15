import re

# Ler arquivo
with open('app/infrastructure/supabase/repositories.py', 'r', encoding='utf-8') as f:
    content = f.read()

# A partir da linha onde os métodos foram alterados (apos __init__), vamos reindentar
# Estratégia: encontrar a linha que define 'def mark_raw_inbound_processed' eeq, mas é complexo.

# Vamos fazer simples: subtrair 2 espaços de todas as linhas que começam com 6 ou mais espaços, mas manter as que já têm 4.
lines = content.split('\n')
new_lines = []
for line in lines:
    # se a linha começa com 6 espaços exatos, ou começa com 6+ espaços e não é comentário?
    # Mas precisa manter struct: métodos da classe têm 4 espaços; métodos internos (dentro de um método) têm 8.
    # No nosso caso, os métodos da classe estão com 6 erroneamente; o interior tem 8,10, etc.
    # Vamos reduzir em 2 espaços todas as linhas que começam com 6 ou mais espaços, exceto if within?
    # Simplificação: se a linha começa com exatamente 6 espaços, substituir por 4.
    # Se começa com 8 espaços, substituir por 6; se começa com 10, por 8; etc.
    stripped = line.lstrip(' ')
    if not stripped:  # linha vazia
        new_lines.append('')
        continue
    # contar espaços iniciais
    leading = len(line) - len(stripped)
    # Se a linha é parte da classe SupabaseRepository (ou seja, depois da linha da classe), e leading >= 6, subtrair 2
    # Para determinar se estamos dentro da classe, podemos marcar após ver "class SupabaseRepository:"
    # Mas vamos assumir que todas as linhas com leading >= 6 e que não são linhas de import (no topo) são erro.
    # No topo, as linhas sem indentação ou com indentação 0 não mudam.
    # As linhas dentro da classe correta têm 4 (métodos) e 8 (corpo). Se encontrar 6, é erro.
    if leading >= 6:
        new_leading = leading - 2
        new_line = ' ' * new_leading + stripped
        new_lines.append(new_line)
    else:
        new_lines.append(line)

new_content = '\n'.join(new_lines)
with open('app/infrastructure/supabase/repositories.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print('Reindentação concluída.')
