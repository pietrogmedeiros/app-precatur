-- Registro dos avisos de infraestrutura já enviados.
--
-- Existe por um motivo só: segurar o aviso de reinício quando o contêiner
-- entra em laço. Sem esta linha, um backend que morre a cada 20 segundos
-- mandaria centenas de e-mails em uma hora — e aviso demais é a forma mais
-- rápida de ninguém mais ler aviso nenhum.
CREATE TABLE IF NOT EXISTS alertas_infra (
  tipo         TEXT        PRIMARY KEY,
  ultimo_envio TIMESTAMPTZ NOT NULL DEFAULT now()
);
