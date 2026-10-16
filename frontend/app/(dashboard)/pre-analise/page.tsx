"use client";

// Pré-Análise — a ferramenta de precatórios do jurídico dentro do app.
//
// A conta NÃO é feita aqui. Esta tela monta o formulário e conversa com o motor
// determinístico (o mesmo que o time já usa), que roda como serviço ao lado.
// Por isso o número é idêntico ao da ferramenta antiga: é o mesmo código.

import { useCallback, useEffect, useState } from "react";
import { Calculator, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Aviso } from "@/components/calculadora/campos";
import { Formulario } from "@/components/calculadora/formulario";
import { Resultado } from "@/components/calculadora/resultado";
import { Documentos } from "@/components/calculadora/documentos";
import { EnviarAoCrm } from "@/components/calculadora/enviar-crm";
import {
  ErroDePreenchimento, FORMULARIO_VAZIO, calcular, estadoCrm, estadoDocumentos,
  memorialPdf, opcoes as carregarOpcoes, saudeDoMotor,
  type EstadoCrm, type EstadoDocumentos, type FormularioCalculo,
  type OpcoesCalculadora, type RespostaCalculo, type SaudeMotor,
} from "@/lib/calculadora";

export default function PreAnalisePage() {
  const [form, setForm] = useState<FormularioCalculo>(FORMULARIO_VAZIO);
  const [opcoes, setOpcoes] = useState<OpcoesCalculadora | null>(null);
  const [saude, setSaude] = useState<SaudeMotor | null>(null);
  const [docs, setDocs] = useState<EstadoDocumentos | null>(null);
  const [crm, setCrm] = useState<EstadoCrm | null>(null);

  const [resposta, setResposta] = useState<RespostaCalculo | null>(null);
  const [calculando, setCalculando] = useState(false);
  const [erros, setErros] = useState<string[]>([]);
  const [falha, setFalha] = useState<string | null>(null);

  // o memorial é um fim em si: dá para baixar o PDF e parar aí, sem CRM nenhum
  const [baixando, setBaixando] = useState(false);
  const [memorialBase64, setMemorialBase64] = useState<string | null>(null);
  const [numerosCrm, setNumerosCrm] = useState<{ numero_precatorio?: string; numero_oficio?: string }>({});
  // O formulário EXATO que gerou o resultado na tela. O envio ao CRM gera o
  // memorial a partir daqui, não do `form` atual: se o advogado mexer num campo
  // sem recalcular, o PDF ainda é o do número que ele conferiu.
  const [formDoCalculo, setFormDoCalculo] = useState<FormularioCalculo | null>(null);

  useEffect(() => {
    carregarOpcoes().then(setOpcoes).catch(() => setOpcoes(null));
    saudeDoMotor().then(setSaude).catch((e) => setFalha(e?.message ?? "Motor indisponível."));
    estadoDocumentos().then(setDocs).catch(() => setDocs(null));
    estadoCrm().then(setCrm).catch(() => setCrm(null));
  }, []);

  const mudar = useCallback((patch: Partial<FormularioCalculo>) => {
    setForm((f) => ({ ...f, ...patch }));
  }, []);

  async function aoCalcular() {
    setCalculando(true);
    setErros([]);
    setFalha(null);
    setMemorialBase64(null);
    try {
      setResposta(await calcular(form));
      setFormDoCalculo(form);
    } catch (e: any) {
      setResposta(null);
      setFormDoCalculo(null);
      if (e instanceof ErroDePreenchimento) setErros(e.erros);
      else setFalha(e?.message ?? "Não foi possível calcular.");
    } finally {
      setCalculando(false);
    }
  }

  // Memorial do resultado que está na tela. Guarda o PDF para o envio ao CRM —
  // o card recebe o MESMO arquivo que o advogado baixou, nunca um gerado depois.
  const obterMemorial = useCallback(async (): Promise<string | null> => {
    if (memorialBase64) return memorialBase64;
    if (!formDoCalculo) return null;
    const { blob } = await memorialPdf(formDoCalculo);
    const b64 = await paraBase64(blob);
    setMemorialBase64(b64);
    return b64;
  }, [memorialBase64, formDoCalculo]);

  async function baixarMemorial() {
    setBaixando(true);
    setFalha(null);
    try {
      const { blob, nome } = await memorialPdf(formDoCalculo ?? form);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = nome;
      a.click();
      URL.revokeObjectURL(url);
      setMemorialBase64(await paraBase64(blob));
    } catch (e: any) {
      if (e instanceof ErroDePreenchimento) setErros(e.erros);
      else setFalha(e?.message ?? "Não foi possível gerar o memorial.");
    } finally {
      setBaixando(false);
    }
  }

  return (
    <div className="space-y-6 p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
            <Calculator className="h-5 w-5" /> Pré-Análise
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Cenário homologado × sentencial, atualização ao presente e período de graça. Nada é
            armazenado: o cálculo acontece e some.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {resposta && (
            <Button variant="outline" onClick={() => { setResposta(null); setErros([]); setMemorialBase64(null); }}>
              <RotateCcw className="h-4 w-4" /> Limpar resultado
            </Button>
          )}
        </div>
      </header>

      {saude && <IndicesPublicados saude={saude} />}
      {falha && <Aviso tom="erro">{falha}</Aviso>}
      {erros.length > 0 && (
        <Aviso tom="erro">
          <ul className="list-inside list-disc space-y-1">
            {erros.map((e) => <li key={e}>{e}</li>)}
          </ul>
        </Aviso>
      )}

      {docs?.habilitado && (
        <Documentos
          estado={docs}
          aoSemear={(patch, numeros) => {
            mudar(patch);
            setNumerosCrm(numeros);
          }}
        />
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start">
        <Formulario form={form} aoMudar={mudar} opcoes={opcoes}
          calculando={calculando} aoCalcular={aoCalcular} />

        <div className="space-y-6 lg:sticky lg:top-6">
          {resposta ? (
            <>
              <Resultado resposta={resposta} aoBaixarMemorial={baixarMemorial}
                baixandoMemorial={baixando} />
              {crm?.bitrix && (
                <EnviarAoCrm
                  estado={crm}
                  resposta={resposta}
                  referencia={form.ref}
                  numeros={numerosCrm}
                  memorialBase64={memorialBase64}
                  obterMemorial={obterMemorial}
                  aoAdotarHonorario={(pct) => mudar({ hc: pct })}
                />
              )}
            </>
          ) : (
            <Card>
              <CardContent className="p-10 text-center text-sm text-muted-foreground">
                Preencha os valores do crédito e clique em <strong>Calcular</strong>.
                O resultado aparece aqui, com a trilha de atualização fase a fase.
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function IndicesPublicados({ saude }: { saude: SaudeMotor }) {
  const meses = Object.entries(saude.indices_ultimo_mes_real).filter(([, v]) => v);
  if (!meses.length) return null;
  return (
    <p className="text-[11px] text-muted-foreground">
      Índices oficiais publicados até:{" "}
      {meses.map(([i, m]) => `${i} ${m}`).join(" · ")}
      {" "}— meses seguintes usam projeção do Boletim Focus e são sinalizados no resultado.
    </p>
  );
}

function paraBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const leitor = new FileReader();
    leitor.onerror = () => reject(new Error("Falha ao ler o PDF."));
    leitor.onload = () => resolve(String(leitor.result).split(",")[1] ?? "");
    leitor.readAsDataURL(blob);
  });
}
