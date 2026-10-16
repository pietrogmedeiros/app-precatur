"use client";

// Envio do resultado para o card do CRM.
//
// Duas regras herdadas da ferramenta original, e as duas existem por um motivo:
// o envio é sempre em DUAS etapas (ensaio e depois gravar), e o que vai para o
// card é o número que está NESTA tela — recalcular no envio deixaria o card
// receber um valor diferente do que o advogado conferiu.

import { useState } from "react";
import { Search, Send, Loader2, ExternalLink } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Aviso, inputClass } from "./campos";
import {
  buscarCards, enviarAoCrm, lerCard,
  type CardCrm, type EstadoCrm, type RespostaCalculo, type RespostaEnvio,
} from "@/lib/calculadora";

export function EnviarAoCrm({
  estado, resposta, referencia, numeros, memorialBase64, obterMemorial, aoAdotarHonorario,
}: {
  estado: EstadoCrm;
  resposta: RespostaCalculo;
  referencia: string;
  numeros: { numero_precatorio?: string; numero_oficio?: string };
  memorialBase64: string | null;
  /** Gera (ou devolve o já gerado) memorial do resultado desta tela, em base64. */
  obterMemorial: () => Promise<string | null>;
  aoAdotarHonorario: (pct: string) => void;
}) {
  const [termo, setTermo] = useState("");
  const [achados, setAchados] = useState<CardCrm[] | null>(null);
  const [card, setCard] = useState<CardCrm | null>(null);
  const [ocupado, setOcupado] = useState<string | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [ensaio, setEnsaio] = useState<RespostaEnvio | null>(null);
  const [gravado, setGravado] = useState<RespostaEnvio | null>(null);
  const [semMemorial, setSemMemorial] = useState<string | null>(null);

  const cen = resposta.resultado.cenario_homologado;
  const liquido = cen.valor_liquido_atualizado;
  const alvo = cen.atualizacao?.data_alvo ?? null;
  // A trava do funil mora no motor e vale para o ENSAIO também. Descobrir isso
  // só ao clicar — e, pior, como um 502 sem explicação — foi o que aconteceu no
  // primeiro uso real: o card estava no funil 0 e o ambiente só escrevia no 9.
  const funisPermitidos = (estado.funis_permitidos?.length
    ? estado.funis_permitidos
    : estado.funil_permitido !== null ? [estado.funil_permitido] : []).map(String);
  const funisTexto = funisPermitidos.join(" ou ");
  const foraDoFunil =
    card !== null && funisPermitidos.length > 0 && card.funil !== undefined &&
    !funisPermitidos.includes(String(card.funil));

  async function tentar(rotulo: string, acao: () => Promise<void>) {
    setOcupado(rotulo); setErro(null);
    try { await acao(); } catch (e: any) { setErro(e?.message ?? "Falhou."); }
    finally { setOcupado(null); }
  }

  // O memorial é anexado SEMPRE — antes dependia de o advogado ter clicado em
  // "Memorial em PDF", e quem enviava direto deixava o card sem o anexo e sem
  // aviso nenhum. Falhar ao gerá-lo não cancela o envio: os campos valem por si.
  async function corpo(aplicar: boolean) {
    let memorial = memorialBase64;
    if (!memorial) {
      try {
        memorial = await obterMemorial();
        setSemMemorial(null);
      } catch (e: any) {
        memorial = null;
        setSemMemorial(e?.message ?? "Não foi possível gerar o memorial.");
      }
    }
    return {
      deal_id: card!.id,
      valor_liquido: liquido,
      honorarios_contratuais_pct: cen.honorarios_contratuais_pct,
      numero_precatorio: numeros.numero_precatorio ?? card?.numero_precatorio ?? null,
      numero_oficio: numeros.numero_oficio ?? null,
      natureza: cen.pss_detalhe ? null : null,
      atualizado_para: alvo,
      aviso_projecao: resposta.aviso_projecao,
      referencia,
      memorial_pdf: memorial,
      aplicar,
    };
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Send className="h-4 w-4" /> Enviar para o card do CRM
        </CardTitle>
        <CardDescription className="text-xs">
          Grava o valor conferido no negócio do Bitrix
          {funisTexto && <> — só no funil {funisTexto}</>}.
          Campo já preenchido no card não é sobrescrito.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <input
            className={inputClass}
            placeholder="Nome do cliente, CPF, ID do negócio ou link do card"
            value={termo}
            onChange={(e) => setTermo(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); buscar(); } }}
          />
          <Button type="button" variant="outline" onClick={buscar} disabled={!termo.trim() || !!ocupado}>
            {ocupado === "buscar" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          </Button>
        </div>

        {achados && achados.length === 0 && (
          <Aviso tom="info">Nenhum card encontrado para “{termo}”.</Aviso>
        )}
        {achados && achados.length > 0 && !card && (
          <div className="space-y-1">
            {achados.map((c) => (
              <button key={c.id} type="button"
                onClick={() => tentar("card", async () => { setCard(await lerCard(c.id)); setEnsaio(null); setGravado(null); })}
                className="block w-full rounded-md border border-border/70 px-3 py-2 text-left text-xs hover:bg-accent">
                <span className="font-medium">#{c.id}</span> — {c.titulo}
                {c.etapa && <span className="text-muted-foreground"> · {c.etapa}</span>}
              </button>
            ))}
          </div>
        )}

        {card && (
          <div className="space-y-3 rounded-md border border-border/70 p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="text-xs">
                <p className="font-medium">#{card.id} — {card.titulo}</p>
                {card.etapa && <p className="text-muted-foreground">{card.etapa}</p>}
              </div>
              {card.url && (
                <a href={card.url} target="_blank" rel="noreferrer"
                  className="inline-flex items-center gap-1 text-xs text-muted-foreground underline">
                  abrir <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </div>

            {foraDoFunil && (
              <Aviso tom="erro">
                Este card está no <strong>funil {card.funil}</strong>, e o envio deste ambiente só
                escreve no <strong>funil {funisTexto}</strong> — nem o ensaio roda. Mova o card, ou
                peça para liberar o funil {String(card.funil)} no envio.
              </Aviso>
            )}

            {card.honorarios_contratuais_pct && card.honorarios_contratuais_pct !== cen.honorarios_contratuais_pct && (
              <Aviso tom="atencao">
                O card declara honorário contratual de {card.honorarios_contratuais_pct}%, diferente do
                que está no cálculo ({cen.honorarios_contratuais_pct ?? "nenhum"}%).{" "}
                <button type="button" className="underline"
                  onClick={() => aoAdotarHonorario(String(card.honorarios_contratuais_pct))}>
                  usar o do card
                </button>
              </Aviso>
            )}

            <div className="rounded bg-muted/60 p-2 text-xs">
              Vai para o card: <strong>{liquido ? `R$ ${Number(liquido).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}` : "—"}</strong>
              {alvo && <> · atualizado até {alvo.split("-").reverse().join("/")}</>}
              <br />
              <span className="text-muted-foreground">
                Com o memorial de cálculo em PDF no anexo “Cálculo Atualizado” — o mesmo
                deste resultado, mesmo sem baixar antes.
              </span>
            </div>

            {semMemorial && (
              <Aviso tom="atencao">
                {semMemorial} O envio segue sem o anexo — os campos do card são gravados
                assim mesmo.
              </Aviso>
            )}

            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" disabled={!!ocupado || foraDoFunil}
                onClick={() => tentar("ensaio", async () => { setEnsaio(await enviarAoCrm(await corpo(false))); setGravado(null); })}>
                {ocupado === "ensaio" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                Conferir (ensaio)
              </Button>
              <Button type="button" disabled={!ensaio || !!ocupado || foraDoFunil}
                onClick={() => tentar("gravar", async () => setGravado(await enviarAoCrm(await corpo(true))))}>
                {ocupado === "gravar" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                Gravar no card
              </Button>
            </div>

            {ensaio && !gravado && <Previa titulo="Ensaio — nada foi gravado ainda" r={ensaio} />}
            {gravado && <Previa titulo={gravado.aplicado ? "Gravado no card" : "Nada novo a gravar"} r={gravado} />}
          </div>
        )}

        {erro && <Aviso tom="erro">{erro}</Aviso>}
      </CardContent>
    </Card>
  );

  function buscar() {
    void tentar("buscar", async () => {
      setCard(null); setEnsaio(null); setGravado(null);
      setAchados((await buscarCards(termo.trim())).cards);
    });
  }
}

function Previa({ titulo, r }: { titulo: string; r: RespostaEnvio }) {
  return (
    <div className="space-y-2 rounded-md bg-muted/50 p-3 text-xs">
      <p className="font-semibold">{titulo}</p>
      {r.ja_rodou_antes && (
        <p className="text-muted-foreground">
          Este card já recebeu uma pré-análise antes — o comentário de auditoria será substituído.
        </p>
      )}
      {r.descricao?.length ? (
        <ul className="list-inside list-disc space-y-0.5 text-muted-foreground">
          {r.descricao.map((d) => <li key={d}>{d}</li>)}
        </ul>
      ) : null}
      {r.detalhe && <p className="text-muted-foreground">{r.detalhe}</p>}
      {r.pulados?.length ? (
        <div>
          <p className="font-medium">Pulados (já preenchidos no card):</p>
          <ul className="list-inside list-disc space-y-0.5 text-muted-foreground">
            {r.pulados.map((p) => <li key={p}>{p}</li>)}
          </ul>
        </div>
      ) : null}
      {r.avisos?.map((a) => <p key={a} className="text-amber-600">{a}</p>)}
    </div>
  );
}
