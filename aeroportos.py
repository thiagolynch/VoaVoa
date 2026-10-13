# -*- coding: utf-8 -*-
"""
aeroportos.py
Aeroportos brasileiros com voos regulares + os 20 destinos internacionais
mais procurados por brasileiros.

- Aeroportos BR: base OurAirports (github.com/davidmegginson/ourairports-data),
  filtro "país = BR, com código IATA e serviço regular". 129 aeroportos.
- Top 20 internacional: posições 1-13 vêm dos rankings de buscas da Decolar
  (jan-fev/2026 e 2º semestre/2025); 14-20 completam com destinos tradicionais
  de alta demanda (EUA e Europa). Revise quando sair um ranking novo.
"""

# (IATA, cidade/aeroporto, UF)
AEROPORTOS_BRASIL = [
    ("CZS", "Cruzeiro do Sul", "AC"),
    ("RBR", "Rio Branco", "AC"),
    ("MCZ", "Maceió", "AL"),
    ("BAZ", "Barcelos", "AM"),
    ("RBB", "Borba", "AM"),
    ("CAF", "Carauari", "AM"),
    ("LBR", "Lábrea", "AM"),
    ("MAO", "Manaus", "AM"),
    ("MNX", "Manicoré", "AM"),
    ("IRZ", "Santa Isabel do Rio Negro", "AM"),
    ("SJL", "São Gabriel da Cachoeira", "AM"),
    ("TBT", "Tabatinga", "AM"),
    ("TFF", "Tefé", "AM"),
    ("MCP", "Macapá", "AP"),
    ("BRA", "Barreiras", "BA"),
    ("IOS", "Ilhéus", "BA"),
    ("LEC", "Lençóis", "BA"),
    ("PAV", "Paulo Afonso", "BA"),
    ("BPS", "Porto Seguro", "BA"),
    ("SSA", "Salvador", "BA"),
    ("UNA", "Una - Comandatuba", "BA"),
    ("VAL", "Valença", "BA"),
    ("VDC", "Vitória da Conquista", "BA"),
    ("JJD", "Jericoacoara (Cruz)", "CE"),
    ("FOR", "Fortaleza", "CE"),
    ("JDO", "Juazeiro do Norte", "CE"),
    ("BSB", "Brasília", "DF"),
    ("GUZ", "Guarapari", "ES"),
    ("VIX", "Vitória", "ES"),
    ("CLV", "Caldas Novas", "GO"),
    ("GYN", "Goiânia", "GO"),
    ("IMP", "Imperatriz", "MA"),
    ("SLZ", "São Luís", "MA"),
    ("AAX", "Araxá", "MG"),
    ("CNF", "Belo Horizonte - Confins", "MG"),
    ("GVR", "Governador Valadares", "MG"),
    ("IPN", "Ipatinga", "MG"),
    ("JDF", "Juiz de Fora - Francisco de Assis", "MG"),
    ("IZA", "Juiz de Fora - Zona da Mata", "MG"),
    ("MOC", "Montes Claros", "MG"),
    ("PYT", "Paracatu", "MG"),
    ("UBA", "Uberaba", "MG"),
    ("UDI", "Uberlândia", "MG"),
    ("BYO", "Bonito", "MS"),
    ("CGR", "Campo Grande", "MS"),
    ("CMG", "Corumbá", "MS"),
    ("PMG", "Ponta Porã", "MS"),
    ("TJL", "Três Lagoas", "MS"),
    ("AFL", "Alta Floresta", "MT"),
    ("CGB", "Cuiabá", "MT"),
    ("ROO", "Rondonópolis", "MT"),
    ("OPS", "Sinop", "MT"),
    ("SMT", "Sorriso", "MT"),
    ("TGQ", "Tangará da Serra", "MT"),
    ("GGF", "Almeirim", "PA"),
    ("ATM", "Altamira", "PA"),
    ("BEL", "Belém", "PA"),
    ("BVS", "Breves", "PA"),
    ("ITB", "Itaituba", "PA"),
    ("MAB", "Marabá", "PA"),
    ("TMT", "Oriximiná - Trombetas", "PA"),
    ("JPE", "Paragominas", "PA"),
    ("CKS", "Parauapebas - Carajás", "PA"),
    ("OPP", "Salinópolis", "PA"),
    ("STM", "Santarém", "PA"),
    ("TUR", "Tucuruí", "PA"),
    ("CJZ", "Cajazeiras", "PB"),
    ("CPV", "Campina Grande", "PB"),
    ("JPA", "João Pessoa", "PB"),
    ("CAU", "Caruaru", "PE"),
    ("FEN", "Fernando de Noronha", "PE"),
    ("PNZ", "Petrolina", "PE"),
    ("REC", "Recife", "PE"),
    ("SET", "Serra Talhada", "PE"),
    ("PHB", "Parnaíba", "PI"),
    ("THE", "Teresina", "PI"),
    ("CAC", "Cascavel", "PR"),
    ("CWB", "Curitiba", "PR"),
    ("IGU", "Foz do Iguaçu", "PR"),
    ("FBE", "Francisco Beltrão", "PR"),
    ("GGJ", "Guaíra", "PR"),
    ("LDB", "Londrina", "PR"),
    ("MGF", "Maringá", "PR"),
    ("PTO", "Pato Branco", "PR"),
    ("PGZ", "Ponta Grossa", "PR"),
    ("TOW", "Toledo", "PR"),
    ("UMU", "Umuarama", "PR"),
    ("UVI", "União da Vitória", "PR"),
    ("CFB", "Cabo Frio", "RJ"),
    ("CAW", "Campos dos Goytacazes", "RJ"),
    ("GIG", "Rio de Janeiro - Galeão", "RJ"),
    ("SDU", "Rio de Janeiro - Santos Dumont", "RJ"),
    ("MVF", "Mossoró", "RN"),
    ("NAT", "Natal", "RN"),
    ("OAL", "Cacoal", "RO"),
    ("JPR", "Ji-Paraná", "RO"),
    ("PVH", "Porto Velho", "RO"),
    ("BVH", "Vilhena", "RO"),
    ("BVB", "Boa Vista", "RR"),
    ("CEL", "Canela", "RS"),
    ("CXJ", "Caxias do Sul", "RS"),
    ("PFB", "Passo Fundo", "RS"),
    ("PET", "Pelotas", "RS"),
    ("POA", "Porto Alegre", "RS"),
    ("RIA", "Santa Maria", "RS"),
    ("SRA", "Santa Rosa", "RS"),
    ("GEL", "Santo Ângelo", "RS"),
    ("URG", "Uruguaiana", "RS"),
    ("XAP", "Chapecó", "SC"),
    ("FLN", "Florianópolis", "SC"),
    ("JJG", "Jaguaruna", "SC"),
    ("JOI", "Joinville", "SC"),
    ("LAJ", "Lages", "SC"),
    ("NVT", "Navegantes", "SC"),
    ("AJU", "Aracaju", "SE"),
    ("AQA", "Araraquara", "SP"),
    ("ARU", "Araçatuba", "SP"),
    ("JTC", "Bauru", "SP"),
    ("VCP", "Campinas - Viracopos", "SP"),
    ("MII", "Marília", "SP"),
    ("PPB", "Presidente Prudente", "SP"),
    ("RAO", "Ribeirão Preto", "SP"),
    ("SOD", "Sorocaba", "SP"),
    ("SJK", "São José dos Campos", "SP"),
    ("SJP", "São José do Rio Preto", "SP"),
    ("GRU", "São Paulo - Guarulhos", "SP"),
    ("CGH", "São Paulo - Congonhas", "SP"),
    ("AUX", "Araguaína", "TO"),
    ("PMW", "Palmas", "TO"),
]

# (IATA, cidade, país, código ISO do país)
DESTINOS_TOP20 = [
    ("SCL", "Santiago", "Chile", "CL"),
    ("EZE", "Buenos Aires", "Argentina", "AR"),
    ("MCO", "Orlando", "Estados Unidos", "US"),
    ("PUJ", "Punta Cana", "República Dominicana", "DO"),
    ("BRC", "Bariloche", "Argentina", "AR"),
    ("LIS", "Lisboa", "Portugal", "PT"),
    ("CDG", "Paris", "França", "FR"),
    ("FCO", "Roma", "Itália", "IT"),
    ("ADZ", "San Andrés", "Colômbia", "CO"),
    ("CUN", "Cancún", "México", "MX"),
    ("CTG", "Cartagena", "Colômbia", "CO"),
    ("LIM", "Lima", "Peru", "PE"),
    ("MVD", "Montevidéu", "Uruguai", "UY"),
    ("MIA", "Miami", "Estados Unidos", "US"),
    ("JFK", "Nova York", "Estados Unidos", "US"),
    ("MAD", "Madri", "Espanha", "ES"),
    ("LHR", "Londres", "Reino Unido", "GB"),
    ("OPO", "Porto", "Portugal", "PT"),
    ("BCN", "Barcelona", "Espanha", "ES"),
    ("MDZ", "Mendoza", "Argentina", "AR"),
]

UFS_BRASIL = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}

# Lista única usada pelo painel e pelo banco: (IATA, nome, UF ou país)
AEROPORTOS = AEROPORTOS_BRASIL + [(iata, cidade, pais) for iata, cidade, pais, _ in DESTINOS_TOP20]

NOMES = {iata: nome for iata, nome, _ in AEROPORTOS}


def _grupos_origem_multi():
    """Cidades brasileiras com mais de um aeroporto (Rio, São Paulo...),
    para oferecer um atalho "selecione os dois de uma vez" no cadastro."""
    por_cidade = {}
    for iata, nome, uf in AEROPORTOS_BRASIL:
        cidade = nome.split(" - ")[0]
        por_cidade.setdefault((cidade, uf), []).append(iata)
    grupos = []
    for (cidade, uf), iatas in por_cidade.items():
        if len(iatas) > 1:
            iatas_ordenados = tuple(sorted(iatas))
            rotulo = f"{cidade} - {uf} ({'+'.join(iatas_ordenados)})"
            grupos.append((f"GRUPO:{'+'.join(iatas_ordenados)}", rotulo, iatas_ordenados))
    return sorted(grupos, key=lambda g: g[1])


GRUPOS_ORIGEM_MULTI = _grupos_origem_multi()
