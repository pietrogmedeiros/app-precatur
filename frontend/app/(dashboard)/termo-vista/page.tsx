"use client";

// Termo de Autorização para Vista e Carga dos Autos — o documento que o closer
// manda o cedente assinar para o jurídico consultar o precatório.
//
// Mesmo molde da proposta: importa do Bitrix o que o card tem, o resto é
// digitado, e o PDF sai pela impressão do navegador. Nada é gravado: o termo
// leva CPF, RG e endereço, e guardar isso não serve a ninguém aqui.
//
// Medido em 29/10/2026 nos 200 cards mais recentes: Nome em 194, CPF em 150 e
// nº do precatório em 149. RG e endereço não vinham preenchidos em nenhum, por
// isso ficam no formulário. Campo em branco sai como linha, para preencher à mão.

import { useState } from "react";
import { Download, FileSignature, Printer, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const inputClass =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-1 focus-visible:ring-ring";

// Os autorizados são fixos: é a equipe do jurídico que faz a análise.
const AUTORIZADOS = [
  { nome: "KEROLLYNN SOUZA CAETANO", genero: "a", oab: "29.420" },
  { nome: "AYRTON LUCAS BRÊDA COLATTO", genero: "o", oab: "33.339" },
  { nome: "VITÓRIA ADAMI ROSSATO RODRIGUES", genero: "a", oab: "40.763" },
  { nome: "MATHEUS DELBONI PEREIRA DAS POSSES", genero: "o", oab: "41.329" },
] as const;

const MESES = [
  "janeiro",
  "fevereiro",
  "março",
  "abril",
  "maio",
  "junho",
  "julho",
  "agosto",
  "setembro",
  "outubro",
  "novembro",
  "dezembro",
];

function hojeIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function dataPorExtenso(iso: string): string | null {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return null;
  return `${parseInt(m[3], 10)} de ${MESES[parseInt(m[2], 10) - 1]} de ${m[1]}`;
}

const VAZIO = {
  nome: "",
  cpf: "",
  rg: "",
  endereco: "",
  precatorio: "",
  local: "",
};

export default function TermoVistaPage() {
  const [campos, setCampos] = useState(VAZIO);
  const [data, setData] = useState(hojeIso);
  const [bitrixRef, setBitrixRef] = useState("");
  const [buscando, setBuscando] = useState(false);
  const [aviso, setAviso] = useState<{
    tom: "ok" | "erro";
    texto: string;
  } | null>(null);

  const mudar =
    (k: keyof typeof VAZIO) => (e: React.ChangeEvent<HTMLInputElement>) =>
      setCampos((c) => ({ ...c, [k]: e.target.value }));

  async function importar() {
    const ref = bitrixRef.trim();
    if (!ref) {
      setAviso({ tom: "erro", texto: "Cole o link ou o ID do deal." });
      return;
    }
    setBuscando(true);
    setAviso(null);
    try {
      const d = await api.bitrixDeal(ref);
      // Parte do termo VAZIO: o que este card não tem não pode ficar do anterior.
      setCampos({
        ...VAZIO,
        local: campos.local,
        // Só o campo Nome: o título do card às vezes leva outra coisa junto.
        nome: d.nomeCompleto ?? "",
        cpf: d.clientDoc ?? "",
        precatorio: d.precatorioNumber ?? "",
      });
      const faltam = [
        !d.nomeCompleto && "nome",
        !d.clientDoc && "CPF",
        !d.precatorioNumber && "nº do precatório",
      ].filter(Boolean);
      setAviso({
        tom: "ok",
        texto:
          `Deal #${d.dealId} importado.` +
          (faltam.length ? ` O card não tem ${faltam.join(", ")}.` : "") +
          " RG e endereço são preenchidos à mão.",
      });
    } catch (e: any) {
      setAviso({ tom: "erro", texto: e.message });
    } finally {
      setBuscando(false);
    }
  }

  function limpar() {
    setCampos(VAZIO);
    setData(hojeIso());
    setBitrixRef("");
    setAviso(null);
  }

  // O Chrome sugere o document.title como nome do arquivo no "Salvar como PDF".
  function gerarPdf() {
    const anterior = document.title;
    const nome = campos.nome
      .trim()
      .replace(/[\/\\:*?"<>|]+/g, "")
      .replace(/\s+/g, "_");
    document.title = nome ? `Termo_de_Vista_${nome}` : "Termo_de_Vista";
    const restaurar = () => {
      document.title = anterior;
      window.removeEventListener("afterprint", restaurar);
    };
    window.addEventListener("afterprint", restaurar);
    window.print();
  }

  const emBranco = (
    [
      ["nome", "nome"],
      ["cpf", "CPF"],
      ["rg", "documento de identidade"],
      ["endereco", "endereço"],
      ["precatorio", "nº do precatório"],
      ["local", "local"],
    ] as const
  )
    .filter(([k]) => !campos[k].trim())
    .map(([, rotulo]) => rotulo);

  return (
    <div className="termo-page mx-auto max-w-6xl space-y-8 p-4 sm:p-6 md:p-8">
      <header className="no-print flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
            <FileSignature className="h-6 w-6" /> Termo de Vista dos Autos
          </h1>
          <p className="text-sm text-muted-foreground">
            Autorização do cedente para o jurídico consultar o precatório. Nada
            é salvo: o PDF sai na hora.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={limpar} className="gap-2">
            <RotateCcw className="h-4 w-4" /> Limpar
          </Button>
          <Button onClick={gerarPdf} className="gap-2">
            <Printer className="h-4 w-4" /> Gerar PDF
          </Button>
        </div>
      </header>

      <div className="termo-layout grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:items-start">
        <div className="no-print space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Download className="h-4 w-4" /> Importar do Bitrix
              </CardTitle>
              <CardDescription>
                Traz nome, CPF e nº do precatório do card.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex gap-2">
                <input
                  className={inputClass}
                  placeholder="Link ou ID do deal"
                  value={bitrixRef}
                  onChange={(e) => setBitrixRef(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") importar();
                  }}
                />
                <Button
                  onClick={importar}
                  disabled={buscando}
                  className="shrink-0"
                >
                  {buscando ? "Buscando…" : "Buscar"}
                </Button>
              </div>
              {aviso ? (
                <p
                  className={
                    aviso.tom === "erro"
                      ? "rounded-md bg-secondary px-3 py-2 text-sm text-red-600 dark:text-red-400"
                      : "rounded-md bg-secondary px-3 py-2 text-sm"
                  }
                >
                  {aviso.texto}
                </p>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Dados do cedente</CardTitle>
              <CardDescription>
                Campo em branco sai como linha no PDF, para o cedente preencher
                à mão.
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Rotulado rotulo="Nome completo" className="sm:col-span-2">
                <input
                  className={inputClass}
                  value={campos.nome}
                  onChange={mudar("nome")}
                />
              </Rotulado>
              <Rotulado rotulo="CPF">
                <input
                  className={inputClass}
                  value={campos.cpf}
                  onChange={mudar("cpf")}
                />
              </Rotulado>
              <Rotulado rotulo="Documento de identidade (RG)">
                <input
                  className={inputClass}
                  value={campos.rg}
                  onChange={mudar("rg")}
                />
              </Rotulado>
              <Rotulado rotulo="Endereço completo" className="sm:col-span-2">
                <input
                  className={inputClass}
                  value={campos.endereco}
                  onChange={mudar("endereco")}
                  placeholder="Rua, número, complemento, bairro, cidade/UF, CEP"
                />
              </Rotulado>
              <Rotulado rotulo="Nº do precatório" className="sm:col-span-2">
                <input
                  className={inputClass}
                  value={campos.precatorio}
                  onChange={mudar("precatorio")}
                />
              </Rotulado>
              <Rotulado rotulo="Local da assinatura">
                <input
                  className={inputClass}
                  value={campos.local}
                  onChange={mudar("local")}
                  placeholder="Ex.: Vitória/ES"
                />
              </Rotulado>
              <Rotulado rotulo="Data">
                <input
                  type="date"
                  className={inputClass}
                  value={data}
                  onChange={(e) => setData(e.target.value)}
                />
              </Rotulado>
              {emBranco.length > 0 && (
                <p className="text-xs text-muted-foreground sm:col-span-2">
                  Em branco no PDF: {emBranco.join(", ")}.
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="termo-preview space-y-3 lg:sticky lg:top-6">
          <p className="no-print text-sm font-medium text-muted-foreground">
            Pré-visualização · 1 página
          </p>
          <Termo campos={campos} data={data} />
        </div>
      </div>
    </div>
  );
}

function Rotulado({
  rotulo,
  className,
  children,
}: {
  rotulo: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`space-y-1.5 ${className ?? ""}`}>
      <label className="text-sm font-medium">{rotulo}</label>
      {children}
    </div>
  );
}

/** Valor digitado, ou uma linha para preencher à mão. */
function V({ v, largura = 14 }: { v: string; largura?: number }) {
  const t = v.trim();
  return t ? (
    <>{t}</>
  ) : (
    <span className="termo-linha" style={{ width: `${largura}em` }} />
  );
}

function Termo({ campos, data }: { campos: typeof VAZIO; data: string }) {
  const extenso = dataPorExtenso(data);
  return (
    <section className="termo-doc">
      <div className="termo-folha">
        <h1 className="termo-titulo">
          TERMO DE AUTORIZAÇÃO PARA VISTA E CARGA DOS AUTOS
        </h1>

        <p>
          Pelo presente instrumento, <V v={campos.nome} largura={18} />,
          inscrito(a) no CPF sob o nº <V v={campos.cpf} largura={9} />,
          portador(a) do documento de identidade nº{" "}
          <V v={campos.rg} largura={9} />, residente e domiciliado(a) à{" "}
          <V v={campos.endereco} largura={24} />, já qualificado(a) nos autos do
          Precatório nº <V v={campos.precatorio} largura={14} />.
        </p>

        <p>
          <strong>AUTORIZA</strong> expressamente{" "}
          {AUTORIZADOS.map((a, i) => (
            <span key={a.oab}>
              {i === AUTORIZADOS.length - 1 ? "e " : ""}
              <strong>{a.nome}</strong>, advogad{a.genero}, inscrit{a.genero} na{" "}
              <strong>OAB/ES</strong> sob o nº <strong>{a.oab}</strong>
              {i < AUTORIZADOS.length - 1 ? "; " : ", "}
            </span>
          ))}
          a consultar e examinar o referido processo, independentemente de
          estarem constituídos nos autos, exclusivamente para fins de análise
          jurídica e documental.
        </p>
        <p>
          A presente autorização compreende o direito de acessar, consultar e
          obter vista integral dos autos, físicos ou eletrônicos, relativos ao
          precatório indicado, bem como de solicitar e obter cópias, realizar
          anotações e extrair informações e documentos necessários à respectiva
          análise jurídica e documental. Tratando-se de autos físicos, fica
          igualmente autorizada a retirada em carga.
        </p>
        <p>
          O presente Termo de Autorização não constitui procuração,
          substabelecimento ou qualquer outro instrumento de outorga de poderes
          para representação processual, restringindo-se às faculdades
          expressamente previstas no parágrafo anterior.
        </p>

        <p className="termo-centro termo-data">
          <V v={campos.local} largura={10} />,{" "}
          {extenso ?? (
            <>
              <span className="termo-linha" style={{ width: "2em" }} /> de{" "}
              <span className="termo-linha" style={{ width: "7em" }} /> de{" "}
              <span className="termo-linha" style={{ width: "3em" }} />
            </>
          )}
          .
        </p>

        <div className="termo-assinatura">
          <div className="termo-assinatura-linha" />
          <div>{campos.nome.trim() || "\u00a0"}</div>
          <div>
            CPF nº{" "}
            {campos.cpf.trim() || (
              <span className="termo-linha" style={{ width: "9em" }} />
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
