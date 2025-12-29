import pandas as pd
import json
import glob
import os
import re

def clean_currency(value):
    if isinstance(value, (int, float)):
        return value
    if not value:
        return 0.0
    # Remove R$, dots and replace comma with dot
    clean = re.sub(r'[^\d,]', '', str(value))
    clean = clean.replace(',', '.')
    try:
        return float(clean)
    except ValueError:
        return 0.0

def load_data(base_dirs):
    all_lots = []
    all_auctions = []
    
    # 1. Carregar Metadados dos Leilões (auctions.json)
    for base_dir in base_dirs:
        # Tenta achar auctions.json na raiz de cada pasta de output
        auctions_file = os.path.join(base_dir, "auctions.json")
        if os.path.exists(auctions_file):
            try:
                with open(auctions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # O arquivo pode ser uma lista de dicts
                    if isinstance(data, list):
                        all_auctions.extend(data)
            except Exception as e:
                print(f"Erro ao ler {auctions_file}: {e}")

    # Cria DataFrame de Leilões
    df_auctions = pd.DataFrame(all_auctions)
    if not df_auctions.empty:
        # Mantém apenas colunas úteis e renomeia para merge
        # Garante que temos as colunas, mesmo que vazias
        cols = ['auction_id', 'number', 'city', 'yard']
        for c in cols:
            if c not in df_auctions.columns:
                df_auctions[c] = None
        
        df_auctions = df_auctions[cols].rename(columns={
            'number': 'leilao_numero',
            'city': 'leilao_cidade',
            'yard': 'leilao_patio'
        })
    
    # 2. Carregar Lotes (lots.jsonl)
    for base_dir in base_dirs:
        pattern = os.path.join(base_dir, "**", "lots.jsonl")
        files = glob.glob(pattern, recursive=True)
        
        print(f"Lendo {len(files)} arquivos de lotes em {base_dir}...")
        
        for fpath in files:
            with open(fpath, 'r', encoding='utf-8') as f:
                for line in f:
                    if not line.strip(): continue
                    try:
                        data = json.loads(line)
                        lot = data.get('lot', data)
                        
                        flat_lot = {
                            'id': lot.get('lot_id'),
                            'descricao': lot.get('description_short'),
                            'modelo': lot.get('brand_model'),
                            'ano': lot.get('year'),
                            'situacao': lot.get('situation'),
                            'lance_inicial': lot.get('start_bid'),
                            'leilao_id': lot.get('auction_id'),
                            'link': lot.get('lot_url')
                        }
                        all_lots.append(flat_lot)
                    except json.JSONDecodeError:
                        continue

    df_lots = pd.DataFrame(all_lots)
    
    # 3. Cruzar Lotes com Leilões (Merge)
    if not df_lots.empty and not df_auctions.empty:
        # Left join para garantir que não perdemos lotes mesmo sem metadata de leilão
        df_merged = pd.merge(df_lots, df_auctions, left_on='leilao_id', right_on='auction_id', how='left')
        return df_merged
    
    return df_lots

def analyze():
    dirs = ['out']
    df = load_data(dirs)
    
    if df.empty:
        print("Nenhum dado encontrado.")
        return

    # Limpeza
    df['lance_inicial'] = df['lance_inicial'].apply(clean_currency)
    df['ano'] = pd.to_numeric(df['ano'], errors='coerce').fillna(0).astype(int)
    
    # Preencher vazios de metadados se o merge falhou ou não existia info
    for col in ['leilao_cidade', 'leilao_numero']:
        if col not in df.columns:
            df[col] = None

    # Fallback: Extrair número do leilão do ID se estiver vazio (ex: ...-2842-2026 -> 2842)
    def extrair_numero_id(row):
        if pd.notna(row['leilao_numero']) and row['leilao_numero'] != 'Desconhecido' and row['leilao_numero'] is not None:
            return row['leilao_numero']
        # Tenta extrair do ID: ...-lotes-2842-2026
        match = re.search(r'-(\d+)-\d{4}$', str(row['leilao_id']))
        if match:
            return match.group(1)
        return 'Desconhecido'

    df['leilao_numero'] = df.apply(extrair_numero_id, axis=1)
    df['leilao_cidade'] = df['leilao_cidade'].fillna('Desconhecido')

    # Remover duplicados (mesmo lote coletado em testes diferentes)
    total_raw = len(df)
    df = df.drop_duplicates(subset=['id'])
    print(f"\nDados carregados: {total_raw} linhas. Únicos: {len(df)} lotes.")

    # --- TRANSFORMAÇÕES PARA EXCEL ---
    
    # 1. Separar Marca e Modelo
    split_modelo = df['modelo'].astype(str).str.split('/', n=1, expand=True)
    df['marca'] = split_modelo[0].str.strip().str.upper()
    df['modelo_veiculo'] = split_modelo[1].str.strip().str.upper()
    df['modelo_veiculo'] = df['modelo_veiculo'].fillna(df['marca'])

    # 2. Limpar Descrição para pegar só "Lote X"
    def extrair_nome_lote(texto):
        if not isinstance(texto, str): return ""
        match = re.search(r'(Lote\s*\d+[a-zA-Z]?)', texto, re.IGNORECASE)
        if match:
            return match.group(1).title()
        return texto

    df['nome_lote'] = df['descricao'].apply(extrair_nome_lote)

    # --- ANÁLISE 5: Lotes Faltantes (Controle de Qualidade) ---
    print("\n=== RELATÓRIO DE LOTES FALTANTES ===")
    
    # Agrupa por leilão (usando leilao_id do DF completo)
    leiloes = df.groupby('leilao_id')
    
    found_gaps = False
    for leilao_id, grupo in leiloes:
        numero_leilao = grupo['leilao_numero'].iloc[0]
        cidade_leilao = grupo['leilao_cidade'].iloc[0]
        
        numeros = []
        for nome in grupo['nome_lote']:
            if not isinstance(nome, str): continue
            match = re.search(r'(\d+)', nome)
            if match:
                numeros.append(int(match.group(1)))
        
        if not numeros: continue
            
        numeros = sorted(list(set(numeros)))
        if not numeros: continue
            
        min_lote = numeros[0]
        max_lote = numeros[-1]
        
        esperados = set(range(min_lote, max_lote + 1))
        encontrados = set(numeros)
        
        faltantes = sorted(list(esperados - encontrados))
        
        if faltantes:
            print(f"Leilão {numero_leilao} ({cidade_leilao}):")
            print(f"  -> Intervalo detectado: {min_lote} a {max_lote}")
            print(f"  -> Faltam {len(faltantes)} lotes: {faltantes}")
            found_gaps = True
            
    if not found_gaps:
        print("Nenhum lote faltando nas sequências encontradas!")

    # --- MONTAGEM DO CSV FINAL ---
    colunas_finais = [
        'leilao_cidade',    # Primary 1
        'leilao_numero',    # Primary 2
        'nome_lote',        
        'situacao',         
        'marca',            
        'modelo_veiculo',   
        'ano',              
        'lance_inicial',    
        'link'              
    ]
    
    # Seleciona apenas as colunas desejadas
    for c in colunas_finais:
        if c not in df.columns:
            df[c] = ''
            
    df_final = df[colunas_finais].copy()

    # --- OUTRAS ANÁLISES (Exibição no Terminal) ---
    print("\n=== RESUMO GERAL ===")
    print(f"Total de Veículos: {len(df)}")
    print(f"Valor Total Inicial: R$ {df['lance_inicial'].sum():,.2f}")
    
    print("\n=== TOP 5 MARCAS ===")
    print(df['marca'].value_counts().head(5))

    print("\n=== OPORTUNIDADES (Honda Conservada, Lance < R$ 1.500) ===")
    oportunidades = df_final[
        (df_final['marca'] == 'HONDA') & 
        (df_final['situacao'] == 'CONSERVADO') & 
        (df_final['lance_inicial'] < 1500)
    ].sort_values('lance_inicial')
    
    if not oportunidades.empty:
        print(oportunidades[['modelo_veiculo', 'ano', 'lance_inicial']].head(5).to_string(index=False))
        print(f"... e mais {len(oportunidades)-5} encontrados.")

    # Exportar
    output_csv = 'relatorio_leiloes.csv'
    df_final.to_csv(output_csv, index=False, sep=';', decimal=',')
    print(f"\nArquivo gerado com sucesso: {output_csv}")
    print("Colunas separadas: [leilao_cidade] [leilao_numero] [nome_lote] [situacao] [marca] [modelo_veiculo] ...")

if __name__ == "__main__":
    analyze()