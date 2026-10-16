"use client";

// Diretrizes de compra — o texto que abre o Mural.
//
// Editável NA PRÓPRIA TELA, e só por admin. O motivo de existir é a frequência:
// elas mudam toda semana, e até agora circulavam por mensagem — quem leu a
// versão de ontem não sabia que era a de ontem. Aqui ficam com data e autor, no
// mesmo lugar onde o time já consulta até que safra pagamos.

import { useEffect, useState } from "react";
import { Megaphone, Pencil, Loader2, Check, X } from "lucide-react";
import { api, type Diretrizes } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const MAX = 8000;

function quando(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.toLocaleDateString("pt-BR")} às ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
}

export function DiretrizesDeCompra({ podeEditar }: { podeEditar: boolean }) {
  const [dados, setDados] = useState<Diretrizes | null>(null);
  const [editando, setEditando] = useState(false);
  const [rascunho, setRascunho] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    api.mural.diretrizes().then(setDados).catch((e) => setErro(e.message));
  }, []);

  async function salvar() {
    setSalvando(true);
    setErro(null);
    try {
      setDados(await api.mural.salvarDiretrizes(rascunho));
      setEditando(false);
    } catch (e: any) {
      setErro(e?.message ?? "Não foi possível salvar.");
    } finally {
      setSalvando(false);
    }
  }

  // Sem texto e sem permissão de editar não há o que mostrar: um cartão vazio
  // só ocuparia o topo do mural de quem não pode fazer nada a respeito.
  if (!dados && !erro) return null;
  if (dados && !dados.texto && !podeEditar) return null;

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 pb-3">
        <div>
          <CardTitle className="flex items-center gap-2 text-base">
            <Megaphone className="h-4 w-4" /> Diretrizes de compra
          </CardTitle>
          {dados?.atualizado_em && !editando && (
            <p className="mt-1 text-xs text-muted-foreground">
              Atualizado em {quando(dados.atualizado_em)}
              {dados.autor ? ` por ${dados.autor}` : ""}.
            </p>
          )}
        </div>
        {podeEditar && !editando && (
          <Button variant="outline" size="sm" className="gap-2"
            onClick={() => { setRascunho(dados?.texto ?? ""); setEditando(true); setErro(null); }}>
            <Pencil className="h-3.5 w-3.5" />
            {dados?.texto ? "Editar" : "Escrever"}
          </Button>
        )}
      </CardHeader>

      <CardContent className="space-y-3">
        {erro && <p className="rounded-md bg-secondary px-3 py-2 text-sm text-red-600 dark:text-red-400">{erro}</p>}

        {editando ? (
          <>
            <textarea
              className="min-h-[180px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm leading-relaxed outline-none focus:ring-1 focus:ring-ring"
              value={rascunho}
              maxLength={MAX}
              autoFocus
              placeholder={"Uma diretriz por linha. Ex.:\n- Não comprar precatório federal com cessão anterior\n- Alimentar de autarquia estadual: consultar o jurídico antes"}
              onChange={(e) => setRascunho(e.target.value)}
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" className="gap-2" onClick={salvar} disabled={salvando}>
                {salvando ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                Salvar
              </Button>
              <Button size="sm" variant="outline" className="gap-2" disabled={salvando}
                onClick={() => { setEditando(false); setErro(null); }}>
                <X className="h-3.5 w-3.5" /> Cancelar
              </Button>
              <span className="text-xs text-muted-foreground">
                {rascunho.length}/{MAX} caracteres · as quebras de linha são preservadas
              </span>
            </div>
          </>
        ) : dados?.texto ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{dados.texto}</p>
        ) : (
          <p className="text-sm text-muted-foreground">
            Nenhuma diretriz publicada ainda. O que você escrever aqui aparece para todo o time,
            no topo do mural.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
