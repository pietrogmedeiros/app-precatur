-- Campos extras da proposta, preenchidos pelo comercial e impressos no PDF.
--
-- ano_pagamento_estado: ano previsto de pagamento pelo ente devedor. O PDF
--   mostra o ano e a espera aproximada em anos, calculada na hora da geração —
--   por isso guardamos só o ano, não o texto derivado.
-- observacoes_proposta: observações que SAEM na proposta. Não confundir com a
--   coluna `observacoes`, que é registro interno e não é impressa.
-- detalhes_processo: informações do processo/precatório, usadas para dar
--   credibilidade quando o destinatário é advogado ou parceiro.
--
-- Todas nullable: propostas antigas seguem válidas e o PDF simplesmente omite
-- as seções vazias.

ALTER TABLE proposals ADD COLUMN IF NOT EXISTS ano_pagamento_estado INTEGER;
ALTER TABLE proposals ADD COLUMN IF NOT EXISTS observacoes_proposta TEXT;
ALTER TABLE proposals ADD COLUMN IF NOT EXISTS detalhes_processo    TEXT;
