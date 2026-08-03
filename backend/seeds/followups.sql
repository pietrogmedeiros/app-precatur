-- Carga inicial da biblioteca de follow-ups (Wiki Sales).
-- Gerado a partir de "consolidado de fups 2.html" — 38 mensagens.
--
-- Seguro rodar mais de uma vez: só insere títulos que ainda não existem.
-- A autoria é atribuída ao usuário admin@precatur.com; se esse e-mail não
-- existir, os registros entram sem autor (só admins poderão editá-los).
--
-- Uso:  psql "$DATABASE_URL" -f backend/seeds/followups.sql
-- Requer que a migration 006_followups.sql já tenha rodado (tabela followups).

WITH autor AS (
  SELECT id, email, name FROM users WHERE email = 'admin@precatur.com' LIMIT 1
), novos (title, body) AS (
  VALUES
    ('Mensagem para corrigir proposta após erro no cálculo do IR', 'Olá, tudo bem?

Quero te pedir desculpas por uma correção importante na proposta que te enviei.

Ao revisar os números com mais atenção, identifiquei que não considerei corretamente o impacto do Imposto de Renda no cálculo final. Por transparência, prefiro te avisar imediatamente e ajustar a proposta da forma correta.

Com essa correção, o valor da proposta sofre uma redução de R$ 4.000,00.

Sei que esse tipo de ajuste não é o ideal depois de uma proposta enviada, por isso faço questão de ser claro e assumir esse ponto com você. Minha intenção é seguir com a negociação de forma séria, transparente e segura para ambos.

Se fizer sentido para você, seguimos com a proposta ajustada e eu fico à disposição para te explicar qualquer detalhe.'),
    ('Mensagem para corrigir proposta após erro no cálculo do IR · Versão mais curta para WhatsApp', 'Olá, tudo bem?

Revisei a proposta com mais cuidado e preciso te pedir desculpas: acabei não considerando corretamente o impacto do IR no cálculo.

Por transparência, o valor final precisa ser ajustado, com uma redução de R$ 4.000,00 em relação à proposta anterior.

Sei que não é o ideal fazer esse ajuste depois, mas prefiro conduzir tudo de forma correta e clara. Se fizer sentido para você, seguimos com a proposta ajustada.'),
    ('Mensagem cordial e firme para tentar reverter cliente que recusou a proposta', 'Olá, tudo bem?

Entendo o seu ponto sobre a proposta e agradeço por ter analisado com atenção.

Ainda assim, gostaria de reforçar alguns pontos que talvez valham ser considerados antes de uma decisão final. Além do valor em si, a proposta oferece liquidez, agilidade e segurança para resolver essa questão sem alongar o processo ou gerar novas incertezas.

Sei que o valor é um fator importante, mas também acredito que a praticidade e a previsibilidade da negociação têm bastante peso.

Se você tiver abertura, posso rever internamente uma condição final para tentar aproximar melhor do que faria sentido para você.'),
    ('Mensagem cordial e firme para tentar reverter cliente que recusou a proposta · Versão mais firme', 'Olá, tudo bem?

Respeito totalmente sua decisão, mas antes de encerrarmos, queria te fazer uma última consideração.

A proposta não considera apenas o valor imediato, mas também a liquidez, a segurança e a agilidade para resolver isso sem burocracia e sem depender de novos interessados ou de um processo mais longo.

Muitas vezes, insistir em um valor maior pode parecer melhor no início, mas também pode significar mais tempo, mais incerteza e menos previsibilidade.

Se ainda houver espaço para conversa, posso avaliar uma condição final para tentarmos chegar em um ponto que faça sentido para ambos.'),
    ('Cliente recebeu proposta e parou de responder há 3 dias', 'Olá, tudo bem?

Passando só para saber se você conseguiu analisar a proposta que te enviei.

Fiquei à disposição porque, caso o ponto principal seja valor, talvez eu consiga rever alguma condição para tentar chegar mais próximo do que faria sentido para você.

Se preferir, posso te ligar rapidamente para explicar melhor e facilitar a análise.'),
    ('Cliente recebeu proposta e parou de responder há 3 dias · Versão mais estratégica, sem entregar aumento logo de cara', 'Olá, tudo bem?

Queria confirmar se você conseguiu ver a proposta que te enviei.

Caso ainda esteja avaliando, fico totalmente à disposição. E se o valor for o principal ponto de dúvida, posso verificar uma condição melhor antes de você tomar uma decisão final.

Acredito que talvez ainda exista espaço para chegarmos em um formato interessante para os dois.'),
    ('Cliente recebeu proposta e parou de responder há 3 dias · Versão com mais urgência', 'Olá, tudo bem?

Estou te chamando porque ainda consigo revisar essa proposta, mas preciso entender se existe interesse da sua parte antes de avançar.

Se o ponto for valor, posso avaliar uma melhora relevante na condição. Só não queria seguir sem antes te dar essa possibilidade.

Se fizer sentido, me avisa e eu te retorno com uma nova condição.'),
    ('Cliente senhora, evasiva, marcou ligação, não atendeu e pediu proposta por WhatsApp', 'Olá, tudo bem?

Espero que esteja bem.

Estou passando apenas para confirmar se a senhora conseguiu ver a proposta que enviei pelo WhatsApp.

Fique tranquila, sem pressa. Caso tenha alguma dúvida ou queira que eu explique algum ponto com mais calma, posso te mandar um áudio ou ligar em um horário melhor para a senhora.

Fico à disposição.'),
    ('Cliente senhora, evasiva, marcou ligação, não atendeu e pediu proposta por WhatsApp · Versão mais objetiva', 'Olá, tudo bem?

A senhora conseguiu analisar a proposta que enviei?

Se tiver alguma dúvida ou quiser conversar com calma, posso te ligar em um horário que seja melhor para a senhora.'),
    ('Cliente senhora, evasiva, marcou ligação, não atendeu e pediu proposta por WhatsApp · Versão com abertura para melhorar proposta', 'Olá, tudo bem?

Passando para saber se a senhora conseguiu analisar a proposta.

Caso o valor seja o principal ponto de dúvida, posso verificar se existe alguma possibilidade de melhorar a condição.

Se preferir, posso explicar tudo com calma por telefone ou por áudio.'),
    ('Consolidado de follow-ups para clientes que receberam proposta e não aceitaram · Follow-up 1 — Confirmação leve', 'Olá, tudo bem?

Passando para saber se você conseguiu analisar a proposta que te enviei.

Fico à disposição caso tenha qualquer dúvida ou queira conversar sobre algum ponto específico.'),
    ('Consolidado de follow-ups para clientes que receberam proposta e não aceitaram · Follow-up 2 — Valor como possível objeção', 'Olá, tudo bem?

Queria entender se a proposta fez sentido para você ou se o principal ponto ficou relacionado ao valor.

Se for esse o caso, posso avaliar internamente se existe alguma margem para melhorar a condição e tentar chegar em algo mais adequado.'),
    ('Consolidado de follow-ups para clientes que receberam proposta e não aceitaram · Follow-up 3 — Reforço de liquidez e segurança', 'Olá, tudo bem?

Só queria reforçar um ponto importante: além do valor da proposta, existe também o benefício da liquidez e da segurança de resolver isso de forma rápida, sem depender de novas negociações, prazos longos ou incertezas.

Às vezes, o melhor negócio não é apenas o maior valor nominal, mas aquele que traz previsibilidade e resolve a situação com tranquilidade.

Se ainda fizer sentido conversarmos, fico à disposição.'),
    ('Consolidado de follow-ups para clientes que receberam proposta e não aceitaram · Follow-up 4 — Última tentativa antes do encerramento', 'Olá, tudo bem?

Estou fazendo um último contato para entender se ainda existe interesse em seguir com a proposta.

Se o ponto principal for valor, posso avaliar uma última condição para tentar aproximar melhor do que você espera.

Caso não faça sentido neste momento, sem problema nenhum. Só não queria encerrar sem antes te dar essa possibilidade.'),
    ('Consolidado de follow-ups para clientes que receberam proposta e não aceitaram · Follow-up 5 — Encerramento cordial', 'Olá, tudo bem?

Como não tivemos avanço na proposta, vou considerar que neste momento não faz sentido para você seguir.

Agradeço pela atenção e pela oportunidade de apresentar a condição.

Deixo meu contato à disposição caso queira retomar a conversa no futuro.'),
    ('Mensagens de encerramento para clientes que não avançaram por valor · Encerramento com porta aberta', 'Olá, tudo bem?

Entendo que neste momento o valor da proposta não ficou dentro do que você esperava.

De qualquer forma, agradeço pela atenção e pela oportunidade de conversar.

Caso mude de ideia ou queira reavaliar mais adiante, fico à disposição para retomarmos.'),
    ('Mensagens de encerramento para clientes que não avançaram por valor · Encerramento com reforço de liquidez', 'Olá, tudo bem?

Entendo sua posição em relação ao valor.

Antes de encerrarmos, só gostaria de reforçar que a proposta também considera liquidez, agilidade e segurança para resolver essa questão sem depender de novas etapas, novos interessados ou prazos incertos.

Ainda assim, respeito sua decisão.

Se em algum momento fizer sentido retomar, fico à disposição.'),
    ('Mensagens de encerramento para clientes que não avançaram por valor · Encerramento mais agudo para tentar reversão', 'Olá, tudo bem?

Respeito totalmente sua decisão, mas quero deixar uma última reflexão antes de encerrarmos.

Buscar um valor maior pode fazer sentido, mas também pode significar mais tempo, mais incerteza e menos liquidez. A proposta que te apresentei tem justamente o objetivo de trazer uma solução mais rápida, segura e previsível.

Se o valor for o único ponto impedindo a decisão, posso fazer uma última avaliação para tentar melhorar a condição.

Caso contrário, agradeço pela conversa e sigo à disposição.'),
    ('Mensagens de encerramento para clientes que não avançaram por valor · Encerramento firme e elegante', 'Olá, tudo bem?

Como não conseguimos avançar dentro das condições conversadas, vou encerrar essa proposta por enquanto.

Agradeço pela atenção e pela oportunidade.

Caso queira retomar no futuro, posso verificar se ainda haverá disponibilidade de condição semelhante, mas não consigo garantir os mesmos termos por muito tempo.'),
    ('Mensagens de encerramento para clientes que não avançaram por valor · Encerramento com senso de oportunidade', 'Olá, tudo bem?

Entendo que o valor não atendeu totalmente sua expectativa.

Só reforço que essa condição foi estruturada considerando uma solução rápida, com liquidez e segurança. Por isso, talvez ela não permaneça disponível nas mesmas bases por muito tempo.

Se quiser reconsiderar, posso tentar manter essa possibilidade aberta por mais um curto período.

Caso contrário, agradeço pela atenção e fico à disposição.'),
    ('Mensagens mais fortes para reverter objeção de valor · Mensagem com foco em custo de oportunidade', 'Olá, tudo bem?

Entendo que o valor seja um ponto importante.

Mas acho válido considerar também o custo de esperar por outra oportunidade. Nem sempre uma proposta maior aparece rapidamente, e muitas vezes ela vem acompanhada de mais prazo, mais negociação e mais incerteza.

A proposta que te apresentei tem como principal vantagem a liquidez: resolver de forma objetiva, segura e com previsibilidade.

Se o valor ainda for o principal obstáculo, posso avaliar uma última condição para tentarmos chegar em um ponto viável.'),
    ('Mensagens mais fortes para reverter objeção de valor · Mensagem com foco em segurança', 'Olá, tudo bem?

Sei que o valor é relevante, mas gostaria de reforçar que a proposta também traz segurança.

Ela evita desgaste, reduz incertezas e permite uma definição mais rápida. Em muitos casos, isso tem um peso tão importante quanto a diferença de valor.

Se fizer sentido, podemos conversar uma última vez para entender se existe um caminho viável para ambos.'),
    ('Mensagens mais fortes para reverter objeção de valor · Mensagem direta para cliente indeciso', 'Olá, tudo bem?

Quero ser bem transparente: se a única questão for valor, talvez ainda exista espaço para uma conversa final.

Mas se a decisão for realmente não seguir, eu entendo perfeitamente.

Só não queria deixar de te procurar antes de encerrar, porque acredito que a proposta ainda pode ser interessante considerando liquidez, rapidez e segurança.'),
    ('Mensagens mais fortes para reverter objeção de valor · Mensagem com proposta de última revisão', 'Olá, tudo bem?

Antes de encerrarmos, posso fazer uma última tentativa de revisão da proposta.

Não consigo prometer que chegaremos exatamente no valor que você espera, mas posso buscar uma condição melhor para tentar viabilizar.

Se houver interesse real em avançar, me avise que eu verifico essa possibilidade.'),
    ('Contato frio com cliente mais velho após mensagem sem resposta · Mensagem após tentativa de ligação', 'Olá, tudo bem?

Tentei te ligar rapidamente para explicar a proposta com mais clareza, mas acho que talvez não tenha sido um bom horário.

Tenho uma condição para te apresentar e acredito que seja mais fácil explicar em uma conversa rápida.

Qual horário seria melhor para eu te ligar?'),
    ('Contato frio com cliente mais velho após mensagem sem resposta · Mensagem mais formal', 'Olá, tudo bem?

Tentei contato por telefone para conversar rapidamente sobre a proposta que tenho para te apresentar.

Como pode envolver alguns detalhes, acredito que uma ligação curta seja a melhor forma de explicar com clareza.

Se puder me indicar um melhor horário, eu retorno no momento mais conveniente.'),
    ('Contato frio com cliente mais velho após mensagem sem resposta · Mensagem simples e respeitosa', 'Olá, tudo bem?

Tenho uma proposta para te apresentar e gostaria de explicar com calma.

Posso te ligar em algum horário melhor para você?'),
    ('Sequência completa pronta para WhatsApp · Dia 0 — Envio da proposta', 'Olá, tudo bem?

Conforme conversamos, estou te enviando a proposta.

Fico à disposição para esclarecer qualquer dúvida e, se preferir, posso te ligar rapidamente para explicar os principais pontos.'),
    ('Sequência completa pronta para WhatsApp · Dia 1 — Confirmação de recebimento', 'Olá, tudo bem?

Só passando para confirmar se você conseguiu ver a proposta que te enviei.

Se tiver qualquer dúvida, fico à disposição.'),
    ('Sequência completa pronta para WhatsApp · Dia 3 — Reforço de análise', 'Olá, tudo bem?

Queria saber se você conseguiu analisar a proposta com calma.

Caso o valor seja algum ponto de dúvida, posso verificar se existe alguma possibilidade de ajuste para tentarmos viabilizar.'),
    ('Sequência completa pronta para WhatsApp · Dia 5 — Ligação ou áudio', 'Olá, tudo bem?

Acredito que talvez seja mais fácil eu te explicar por ligação ou áudio rápido.

Posso te ligar em algum horário melhor para você?'),
    ('Sequência completa pronta para WhatsApp · Dia 7 — Última tentativa comercial', 'Olá, tudo bem?

Estou fazendo um último contato para entender se ainda existe interesse em seguir.

Se o ponto principal for valor, posso avaliar uma última condição para tentar aproximar melhor do que você espera.

Caso não faça sentido, sem problema. Só não queria encerrar sem antes te dar essa possibilidade.'),
    ('Sequência completa pronta para WhatsApp · Dia 10 — Encerramento', 'Olá, tudo bem?

Como não tivemos avanço, vou considerar que neste momento não faz sentido seguir com a proposta.

Agradeço pela atenção e deixo meu contato à disposição caso queira retomar futuramente.'),
    ('Opções de tom para diferentes perfis de cliente · Cliente direto e objetivo', 'Olá, tudo bem?

Conseguiu avaliar a proposta?

Se o ponto for valor, posso verificar uma última condição para tentar viabilizar.'),
    ('Opções de tom para diferentes perfis de cliente · Cliente mais velho ou cauteloso', 'Olá, tudo bem?

Espero que esteja bem.

A senhora conseguiu analisar a proposta que enviei?

Se tiver qualquer dúvida, posso explicar com calma por telefone ou por áudio.'),
    ('Opções de tom para diferentes perfis de cliente · Cliente evasivo', 'Olá, tudo bem?

Estou te chamando apenas para entender se ainda faz sentido mantermos essa proposta em aberto.

Caso tenha interesse, posso verificar uma condição final. Se não for o momento, sem problema nenhum.'),
    ('Opções de tom para diferentes perfis de cliente · Cliente que recusou por preço', 'Olá, tudo bem?

Entendo seu ponto sobre o valor.

Ainda assim, acredito que vale considerar os benefícios da proposta: liquidez, agilidade e segurança para resolver isso sem alongar o processo.

Se houver abertura, posso tentar uma última revisão.'),
    ('Opções de tom para diferentes perfis de cliente · Cliente sumido após proposta', 'Olá, tudo bem?

Passando para saber se você conseguiu ver minha proposta.

Se ainda estiver avaliando, fico à disposição. E caso o valor seja o ponto principal, posso verificar se existe alguma possibilidade de ajuste.')
)
INSERT INTO followups (title, body, created_by_id, created_by, created_by_name)
SELECT n.title, n.body, a.id, a.email, a.name
  FROM novos n
  LEFT JOIN autor a ON true
 WHERE NOT EXISTS (SELECT 1 FROM followups f WHERE f.title = n.title);
