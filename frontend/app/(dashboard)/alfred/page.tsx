"use client";

// Alfred — a base de consulta de precatórios dentro do app.
//
// Duas perguntas, duas abas: "este crédito, quanto vale e quando paga?" e "este
// devedor, paga?". A busca por CPF vai por POST de propósito: o log de acesso
// registra o caminho da requisição, e CPF em query string iria parar no log.

import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, Database, Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Opcoes, inputClass } from "@/components/calculadora/campos";
import { ParecerView } from "@/components/alfred/parecer";
import { AbaEnte } from "@/components/alfred/ente";
import {
  brl, brlCurto, numero, buscar, eu as quemSouEu, parecerPorId, parecerPdf, saude,
  type Eu, type ItemBusca, type Parecer, type RespostaBusca, type SaudeAlfred,
} from "@/lib/alfred";

type Aba = "precatorio" | "ente";

export default function AlfredPage() {
  const [aba, setAba] = useState<Aba>("precatorio");
  const [quem, setQuem] = useState<Eu | null>(null);
  const [base, setBase] = useState<SaudeAlfred | null>(null);
  const [falha, setFalha] = useState<string | null>(null);

  useEffect(() => {
    quemSouEu().then(setQuem).catch(() => setQuem(null));
    saude().then(setBase).catch((e) => setFalha(e?.message ?? "Base indisponível."));
  }, []);

  return (
    <div className="space-y-6 p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <Database className="h-5 w-5" /> Alfred
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Consulta de precatórios: posição na fila, comportamento do devedor e projeção de pagamento.
          </p>
        </div>
        {base?.ok && (
          <p className="text-[11px] text-muted-foreground">
            {numero(base.precatorios)} precatórios na base
            {quem?.papel === "leitor" && " · CPF mascarado para o seu perfil"}
          </p>
        )}
      </header>

      {falha && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {falha}
        </div>
      )}
      {quem && !quem.configurado && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-300">
          A consulta não está configurada neste ambiente (faltam os tokens do Alfred).
        </div>
      )}

      <Opcoes<Aba>
        label="O que você quer consultar"
        valor={aba}
        onChange={setAba}
        opcoes={[
          { valor: "precatorio", rotulo: "Precatório" },
          { valor: "ente", rotulo: "Ente devedor" },
        ]}
      />

      {aba === "precatorio"
        ? <AbaPrecatorio papel={quem?.papel ?? "leitor"} />
        : <AbaEnteComParecer papel={quem?.papel ?? "leitor"} />}
    </div>
  );
}

/** A aba do ente sabe abrir um parecer quando se clica numa linha da fila. */
function AbaEnteComParecer({ papel }: { papel: "leitor" | "completo" }) {
  const [aberto, setAberto] = useState<number | null>(null);
  if (aberto !== null) {
    return <Detalhe id={aberto} papel={papel} aoVoltar={() => setAberto(null)} />;
  }
  return <AbaEnte aoAbrirPrecatorio={setAberto} />;
}

function AbaPrecatorio({ papel }: { papel: "leitor" | "completo" }) {
  const [termo, setTermo] = useState("");
  const [resposta, setResposta] = useState<RespostaBusca | null>(null);
  const [pagina, setPagina] = useState(1);
  const [buscando, setBuscando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [aberto, setAberto] = useState<number | null>(null);

  const procurar = useCallback(async (p = 1) => {
    const t = termo.trim();
    if (t.length < 3) { setErro("Informe ao menos 3 caracteres."); return; }
    setBuscando(true); setErro(null);
    try {
      const r = await buscar(t, p);
      setResposta(r); setPagina(p);
      // Resultado único: abre direto, que é o que se quer ao colar um número.
      if (r.itens.length === 1 && p === 1) setAberto(r.itens[0].id);
    } catch (e: any) {
      setResposta(null);
      setErro(e?.message ?? "Não foi possível consultar.");
    } finally {
      setBuscando(false);
    }
  }, [termo]);

  if (aberto !== null) {
    return <Detalhe id={aberto} papel={papel} aoVoltar={() => setAberto(null)} />;
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <input
          className={inputClass}
          placeholder="Nº do precatório, nº de origem, CPF/CNPJ ou nome do credor"
          value={termo}
          onChange={(e) => setTermo(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); void procurar(1); } }}
        />
        <Button type="button" onClick={() => void procurar(1)} disabled={buscando}>
          {buscando ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          Buscar
        </Button>
      </div>

      {erro && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">{erro}</div>
      )}

      {resposta && resposta.itens.length === 0 && (
        <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">
          {resposta.explicacao ?? "Nada encontrado para esse termo."}
        </CardContent></Card>
      )}

      {resposta && resposta.itens.length > 0 && (
        <>
          <p className="text-xs text-muted-foreground">
            {numero(resposta.total_encontrado)} resultado(s) por <strong>{resposta.criterio}</strong>
            {resposta.paginas > 1 && ` · página ${resposta.pagina} de ${numero(resposta.paginas)}`}
          </p>
          <div className="overflow-hidden rounded-md border border-border/70">
            <table className="w-full text-xs">
              <thead className="bg-muted/70 text-left">
                <tr>
                  <th className="px-3 py-2 font-medium">Credor</th>
                  <th className="px-3 py-2 font-medium">Devedor</th>
                  <th className="px-3 py-2 font-medium">Tribunal</th>
                  <th className="px-3 py-2 text-right font-medium">Fila</th>
                  <th className="px-3 py-2 text-right font-medium">Valor</th>
                </tr>
              </thead>
              <tbody>
                {resposta.itens.map((i) => <LinhaResultado key={i.id} item={i} aoAbrir={() => setAberto(i.id)} />)}
              </tbody>
            </table>
          </div>
          {resposta.paginas > 1 && (
            <div className="flex items-center justify-center gap-2">
              <Button size="sm" variant="outline" disabled={pagina <= 1 || buscando}
                onClick={() => void procurar(pagina - 1)}>Anterior</Button>
              <span className="text-xs text-muted-foreground">{pagina} / {numero(resposta.paginas)}</span>
              <Button size="sm" variant="outline" disabled={pagina >= resposta.paginas || buscando}
                onClick={() => void procurar(pagina + 1)}>Próxima</Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function LinhaResultado({ item, aoAbrir }: { item: ItemBusca; aoAbrir: () => void }) {
  return (
    <tr onClick={aoAbrir} className="cursor-pointer border-t border-border/50 hover:bg-accent">
      <td className="px-3 py-2">
        <span className="block">{item.credor ?? <span className="text-muted-foreground">não publicado</span>}</span>
        <span className="block font-mono text-[10px] text-muted-foreground">{item.numero}</span>
      </td>
      <td className="px-3 py-2">{item.municipio ?? "—"}{item.uf ? ` / ${item.uf}` : ""}</td>
      <td className="px-3 py-2">{item.tribunal}</td>
      <td className="px-3 py-2 text-right tabular-nums">{item.ordem ? numero(item.ordem) : "—"}</td>
      <td className="px-3 py-2 text-right tabular-nums">{brl(item.valor)}</td>
    </tr>
  );
}

function Detalhe({
  id, papel, aoVoltar,
}: {
  id: number; papel: "leitor" | "completo"; aoVoltar: () => void;
}) {
  const [parecer, setParecer] = useState<Parecer | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [revelado, setRevelado] = useState(false);
  const [baixando, setBaixando] = useState(false);

  const carregar = useCallback((completo: boolean) => {
    setErro(null);
    parecerPorId(id, completo)
      .then((r) => setParecer({ ...r.pareceres[0], id }))
      .catch((e) => setErro(e?.message ?? "Não foi possível abrir o parecer."));
  }, [id]);

  useEffect(() => { carregar(false); setRevelado(false); }, [carregar]);

  async function baixar() {
    setBaixando(true);
    try {
      const { blob, nome } = await parecerPdf(id, revelado);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = nome; a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setErro(e?.message ?? "Não foi possível gerar o PDF.");
    } finally {
      setBaixando(false);
    }
  }

  return (
    <div className="space-y-4">
      <Button size="sm" variant="ghost" onClick={aoVoltar}>
        <ArrowLeft className="h-4 w-4" /> voltar aos resultados
      </Button>
      {erro && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">{erro}</div>
      )}
      {!parecer && !erro && (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> montando o parecer…
        </p>
      )}
      {parecer && (
        <ParecerView
          parecer={parecer}
          papel={papel}
          revelado={revelado}
          aoRevelar={() => { setRevelado(true); carregar(true); }}
          aoBaixarPdf={baixar}
          baixando={baixando}
        />
      )}
    </div>
  );
}
