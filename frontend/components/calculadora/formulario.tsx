"use client";

// O formulário da calculadora — as mesmas seções, na mesma ordem e com as mesmas
// ajudas da ferramenta que o time já usa. A numeração muda com o modo (ofício
// tem 5 seções; originário tem 6, por causa do regime de correção), igual lá.

import { Card, CardContent } from "@/components/ui/card";
import {
  Aviso, Campo, CampoData, CampoSelect, CampoTexto, Opcoes, Secao, inputClass,
} from "./campos";
import type { FormularioCalculo, ModoIr, ModoPss, OpcoesCalculadora } from "@/lib/calculadora";

const NATUREZAS_HIST: Record<string, string> = {
  "": "(usar índice SGS abaixo)",
  comum: "comum — condenatória geral",
  servidor: "servidor — remuneratório",
  previdenciario: "previdenciario — benefício",
  tributario: "tributario — repetição de indébito",
  desapropriacao: "desapropriacao — moratórios 6% a.a.",
  assistencial: "assistencial — BPC/LOAS",
};

const NATUREZAS_TRIB: Record<string, string> = {
  "": "(não informar)",
  remuneratorio: "remuneratorio — salários / vencimentos",
  previdenciario: "previdenciario — aposentadoria / pensão",
  indenizatorio: "indenizatorio — dano / verba indenizatória",
  misto: "misto — mistura tributável e não-tributável",
};

export function Formulario({
  form, aoMudar, opcoes, calculando, aoCalcular,
}: {
  form: FormularioCalculo;
  aoMudar: (patch: Partial<FormularioCalculo>) => void;
  opcoes: OpcoesCalculadora | null;
  calculando: boolean;
  aoCalcular: () => void;
}) {
  const ehConta = form.modo === "oficio";
  // Numeração acompanha o que está na tela, como no app original.
  let n = 0;
  const prox = () => ++n;

  const entes = [
    { valor: "", rotulo: "(não informar)" },
    ...(opcoes?.entes ?? []).map((e) => ({ valor: e, rotulo: e })),
    { valor: "outro", rotulo: "Outro (digitar abaixo)" },
  ];
  const anos = [
    { valor: "", rotulo: "(não informar)" },
    ...(opcoes?.anos_orcamentarios ?? []).map((a) => ({ valor: a, rotulo: a })),
  ];

  return (
    <Card>
      <CardContent className="space-y-8 p-6">
        <Opcoes<FormularioCalculo["modo"]>
          label="Ponto de partida"
          valor={form.modo}
          onChange={(v) => aoMudar({ modo: v })}
          opcoes={[
            { valor: "oficio", rotulo: "Modo ofício (valores homologados)" },
            { valor: "originario", rotulo: "Modo originário (liquidar do zero)" },
          ]}
          ajuda="Ofício: todos os ofícios trazem valores já liquidados/homologados. Originário: começa do valor de origem + regime."
        />

        <Secao numero={prox()} titulo="Valores do crédito">
          {ehConta ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <CampoTexto label="Valor Total Requisitado (R$)" placeholder="0,00" inputMode="decimal"
                valor={form.vt} onChange={(v) => aoMudar({ vt: v })}
                ajuda="Valor homologado do crédito do credor (já sem cota patronal)." />
              <CampoTexto label="Juros (moratórios) (R$)" placeholder="0,00" inputMode="decimal"
                valor={form.vj} onChange={(v) => aoMudar({ vj: v })}
                ajuda="Linha de juros do ofício, se destacada." />
              <CampoTexto label="Principal Corrigido (R$)" placeholder="0,00" inputMode="decimal"
                valor={form.vp} onChange={(v) => aoMudar({ vp: v })}
                ajuda="Base do PSS, do IR e da atualização." />
              <CampoTexto label="SELIC (R$)" placeholder="0,00" inputMode="decimal"
                valor={form.vs} onChange={(v) => aoMudar({ vs: v })}
                ajuda="Se o ofício já traz a SELIC num campo próprio." />
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <CampoTexto label="Valor originário (R$)" placeholder="0,00" inputMode="decimal"
                valor={form.vo} onChange={(v) => aoMudar({ vo: v })}
                ajuda="Valor de origem, antes de qualquer correção." />
              <p className="self-center text-xs text-muted-foreground">
                O regime da seção 2 corrige o originário até a data do cálculo.
              </p>
            </div>
          )}

          {ehConta ? (
            <CampoData label="Data-base" valor={form.data_calculo}
              onChange={(v) => aoMudar({ data_calculo: v })}
              ajuda="Data-base do ofício: data em que os valores acima estão expressos. A atualização parte daqui."
              className="sm:max-w-xs" />
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <CampoData label="Data-base" valor={form.data_base} onChange={(v) => aoMudar({ data_base: v })}
                ajuda="Marco inicial da correção. Motor histórico cobre desde out/1964; índices SGS desde jan/2000." />
              <CampoData label="Data do cálculo" valor={form.data_calculo}
                onChange={(v) => aoMudar({ data_calculo: v })}
                ajuda="Até quando corrigir o originário (≥ data-base)." />
            </div>
          )}
        </Secao>

        {!ehConta && (
          <Secao numero={prox()} titulo="Regime de correção">
            <CampoSelect label="Correção por natureza (motor histórico — cobre desde 1964)"
              valor={form.nat_hist} onChange={(v) => aoMudar({ nat_hist: v })}
              opcoes={Object.entries(NATUREZAS_HIST).map(([valor, rotulo]) => ({ valor, rotulo }))}
              ajuda="Corrige o originário do ZERO pela fase de condenação (Temas 810/905). Deixe no SGS para o regime simples/composto declarado." />
            {form.nat_hist === "assistencial" && (
              <CampoSelect label="Índice (BPC/LOAS)" valor={form.assist_idx}
                onChange={(v) => aoMudar({ assist_idx: v })}
                opcoes={[{ valor: "IPCA-E", rotulo: "IPCA-E" }, { valor: "INPC", rotulo: "INPC" }]}
                ajuda="Decisão jurídica: o Tema 810 aponta IPCA-E." className="sm:max-w-xs" />
            )}
            {!form.nat_hist && (
              <CampoSelect label="Regime (índice SGS)" valor={form.regime}
                onChange={(v) => aoMudar({ regime: v })}
                opcoes={(opcoes?.regimes ?? []).map((r) => ({ valor: r.valor, rotulo: r.rotulo }))}
                ajuda="Como corrigir o valor originário até a data do cálculo." />
            )}
          </Secao>
        )}

        <Secao numero={prox()} titulo="Natureza e tributação (PSS / IR)">
          <CampoSelect label="Natureza do Crédito" valor={form.natureza}
            onChange={(v) => aoMudar({ natureza: v })}
            opcoes={Object.entries(NATUREZAS_TRIB).map(([valor, rotulo]) => ({ valor, rotulo }))}
            ajuda="Remuneratório: incide PSS e IR. Previdenciário: só IR. Indenizatório: nenhum. Misto: fica 'a apurar'." />

          <div className="grid gap-6 sm:grid-cols-2">
            <div className="space-y-3">
              <p className="text-xs font-semibold">Contribuições (previdência / assistência)</p>
              <Opcoes<ModoPss> label="" valor={form.pss_modo} onChange={(v) => aoMudar({ pss_modo: v })}
                opcoes={[
                  { valor: "nao", rotulo: "Não descontar" },
                  { valor: "valor", rotulo: "Valor no ofício (R$)" },
                  { valor: "aliquota", rotulo: "Por alíquota (%)" },
                ]} />
              <CampoTexto label="↳ Valor das contribuições (R$)" placeholder="0,00" inputMode="decimal"
                valor={form.pss} onChange={(v) => aoMudar({ pss: v })} />
              <CampoTexto label="↳ Alíquota (%)" placeholder="14" inputMode="decimal"
                valor={form.apss} onChange={(v) => aoMudar({ apss: v })}
                ajuda="Padrão 14%. Para não descontar PSS, escolha 'Não descontar'." />
            </div>

            <div className="space-y-3">
              <p className="text-xs font-semibold">Imposto de Renda a deduzir</p>
              <Opcoes<ModoIr> label="" valor={form.ir_modo} onChange={(v) => aoMudar({ ir_modo: v })}
                opcoes={[
                  { valor: "nao", rotulo: "Não descontar" },
                  { valor: "valor", rotulo: "Valor no ofício (R$)" },
                  { valor: "estimar", rotulo: "Estimar por natureza" },
                ]} />
              <CampoTexto label="↳ Valor do IR (R$)" placeholder="0,00" inputMode="decimal"
                valor={form.ir} onChange={(v) => aoMudar({ ir: v })} />
              <Campo label="↳ Número de meses (RRA)"
                ajuda="Dilui a base do IR-RRA. Sem os meses, o IR estimado fica 'a apurar' em vez de inflar.">
                <input type="number" min={0} step={1} className={inputClass}
                  value={form.meses} onChange={(e) => aoMudar({ meses: e.target.value })} />
              </Campo>
            </div>
          </div>
        </Secao>

        <Secao numero={prox()} titulo="Honorários">
          <div className="grid gap-4 sm:grid-cols-2">
            <CampoTexto label="Honorários Contratuais (%)" placeholder="20" inputMode="decimal"
              valor={form.hc} onChange={(v) => aoMudar({ hc: v })}
              ajuda="Descontado no FINAL, sobre o valor atualizado — entra no memorial como linha própria, igual PSS e IR." />
            <CampoTexto label="Honorários de Sucumbência (%)" placeholder="10" inputMode="decimal"
              valor={form.hs} onChange={(v) => aoMudar({ hs: v })}
              ajuda="NÃO sai do líquido do credor. Vai para o memorial, com o valor sobre o bruto atualizado e o IR de 27,5%." />
          </div>
          {!form.hc && (
            <Aviso tom="atencao">
              Sem honorário contratual não há desconto e o valor final é o <strong>BRUTO</strong>.
              Ele vem do contrato com o cliente, não dos autos.
            </Aviso>
          )}
        </Secao>

        <Secao numero={prox()} titulo="Precatório e período de graça">
          <div className="grid gap-4 sm:grid-cols-2">
            <CampoSelect label="Espécie da requisição" valor={form.modalidade}
              onChange={(v) => aoMudar({ modalidade: v })}
              opcoes={[
                { valor: "", rotulo: "(não informar)" },
                { valor: "precatorio", rotulo: "precatorio" },
                { valor: "rpv", rotulo: "rpv" },
              ]} />
            <CampoData label="Data de apresentação do ofício ao tribunal" valor={form.data_apres}
              onChange={(v) => aoMudar({ data_apres: v })}
              ajuda="Âncora do período de graça (art. 100 §5º CF + SV 17). O corte varia por época: 1º/07 até 2021, 02/04 (2022-2025), 1º/02 (2026+)." />
            <CampoTexto label="Superpreferência paga (R$)" placeholder="0,00" inputMode="decimal"
              valor={form.sp_val} onChange={(v) => aoMudar({ sp_val: v })}
              ajuda="Antecipação já recebida (idoso 80+/doença grave/PcD). Valor BRUTO — abatido do saldo corrigido na data do pagamento." />
            <CampoData label="Data do pagamento da superpreferência" valor={form.sp_data}
              onChange={(v) => aoMudar({ sp_data: v })} />
            <CampoSelect label="Ente/Entidade devedora" valor={form.ente}
              onChange={(v) => aoMudar({ ente: v })} opcoes={entes}
              ajuda="Quem paga o precatório. Se não estiver na lista, escolha 'Outro' e digite abaixo." />
            <CampoSelect label="Ano orçamentário" valor={form.ano_orc}
              onChange={(v) => aoMudar({ ano_orc: v })} opcoes={anos}
              ajuda="Exercício em que o precatório entra na proposta orçamentária do ente (art. 100 CF)." />
          </div>
          {form.ente === "outro" && (
            <CampoTexto label="↳ Entidade devedora" placeholder="ex.: Município de Vitória / DER-ES"
              valor={form.ente_outro} onChange={(v) => aoMudar({ ente_outro: v })} />
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <CampoData label="Data de expedição do ofício" valor={form.data_expedicao}
              onChange={(v) => aoMudar({ data_expedicao: v })}
              ajuda="Só importa para conta ANTERIOR a dez/2021. Expedido até 25/03/2015 usa TR na janela dez/2009–mar/2015. Vazio = usa IPCA-E." />
            <CampoSelect label="Esfera do ente devedor" valor={form.esfera}
              onChange={(v) => aoMudar({ esfera: v as FormularioCalculo["esfera"] })}
              opcoes={[
                { valor: "auto", rotulo: "Auto (deduz pelo ente)" },
                { valor: "estadual", rotulo: "Estadual / Municipal / DF" },
                { valor: "federal", rotulo: "Federal (União / INSS / autarquia federal)" },
              ]}
              ajuda="Muda uma só coisa: o mês em que a correção passa a ser IPCA + 2% a.a. da EC 136 — federais em set/2025, estaduais/municipais em ago/2025." />
          </div>
        </Secao>

        <Secao numero={prox()} titulo="Atualização ao presente">
          <div className="grid gap-4 sm:grid-cols-2">
            <CampoData label="Data de atualização" valor={form.data_alvo}
              onChange={(v) => aoMudar({ data_alvo: v })}
              ajuda="Até quando atualizar (padrão: hoje). Recua se passar da cobertura do BACEN." />
            <CampoTexto label="Nº do processo / requisição"
              placeholder="ex.: Precatório nº ... - Fulano de Tal"
              valor={form.ref} onChange={(v) => aoMudar({ ref: v })} />
          </div>
          <Campo label="Observações Gerais" ajuda="Anotações do advogado que devem constar no PDF.">
            <textarea className={`${inputClass} h-24 py-2`} value={form.obs}
              onChange={(e) => aoMudar({ obs: e.target.value })} />
          </Campo>
        </Secao>

        <button
          type="button"
          onClick={aoCalcular}
          disabled={calculando}
          className="inline-flex h-10 w-full items-center justify-center rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground shadow transition-colors hover:bg-primary/90 disabled:opacity-60"
        >
          {calculando ? "Calculando…" : "Calcular"}
        </button>
      </CardContent>
    </Card>
  );
}
