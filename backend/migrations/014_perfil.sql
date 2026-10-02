-- Perfil do usuário: nome editável pelo próprio e foto.
--
-- A foto fica como data URI em TEXT, e não em disco: o contêiner do EasyPanel é
-- recriado a cada deploy e arquivo em disco sumiria. A tela reduz a imagem para
-- 256px antes de enviar, então cada foto fica na casa de dezenas de KB — pequena
-- o bastante para viajar junto do /auth/me e aparecer no menu sem outra chamada.

ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar TEXT;
