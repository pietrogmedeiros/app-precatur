"use client";

import { useEffect, useRef, useState } from "react";
import { Calculator, Loader2, Info, ArrowRight, ShieldCheck, MessageCircle } from "lucide-react";
import {
  calcularPrecatorio, safrasDaPraca, verificarCodigo, reenviarCodigo,
  type CalculoResposta, type CalculoPendente,
} from "@/lib/api";
import { formatBRL, parseBRL } from "@/lib/pricing";
import { fechaMoeda, maskMoeda, maskProcesso, maskTelefone } from "@/lib/masks";
import { Button } from "@/components/ui/button";

const UFS = ["AC","AL","AM","AP","BA","CE","DF","ES","GO","MA","MG","MS","MT","PA","PB","PE","PI","PR","RJ","RN","RO","RR","RS","SC","SE","SP","TO"];

const inputClass =
  "flex h-10 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

export default function CalcularPage() {
  // O valor só aparece depois que o telefone é confirmado por WhatsApp, então a
  // página tem três momentos: preencher, confirmar o código e ver o resultado.
  const [etapa, setEtapa] = useState<"form" | "codigo" | "resultado">("form");

  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [telefone, setTelefone] = useState("");
  const [processo, setProcesso] = useState("");

  const [esfera, setEsfera] = useState<"federal" | "estadual" | "municipal">("estadual");
  const [uf, setUf] = useState("");
  const [municipio, setMunicipio] = useState("");
  const [safras, setSafras] = useState<string[]>([]);
  const [ativos, setAtivos] = useState<string[]>([]);
  const [praca, setPraca] = useState<{ label: string; estimativa: boolean } | null>(null);
  const [safra, setSafra] = useState("");
  const [ativo, setAtivo] = useState("");
  const [natureza, setNatureza] = useState<"alimentar" | "comum">("alimentar");

  const [v, setV] = useState({ principal: "", juros: "", selic: "", pss: "", preferencia: "", outras: "" });
  const [honorarios, setHonorarios] = useState("30");
  const [ir, setIr] = useState("0");
  const [irBase, setIrBase] = useState<"principal" | "bruto">("principal");

  const [pendente, setPendente] = useState<CalculoPendente | null>(null);
  const [resultado, setResultado] = useState<CalculoResposta | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const num = (s: string) => parseBRL(s);
  const bruto = num(v.principal) + num(v.juros) + num(v.selic);
  // As deduções são conferidas aqui, antes de disparar o WhatsApp: não faz
  // sentido gastar um código para entregar um resultado zerado.
  const pctHon = Number(honorarios.replace(",", ".")) || 0;
  const pctIr = Number(ir.replace(",", ".")) || 0;
  const deducoes =
    bruto * (pctHon / 100) +
    (irBase === "bruto" ? bruto : num(v.principal)) * (pctIr / 100) +
    num(v.pss) + num(v.preferencia) + num(v.outras);
  const deducoesExcedem = bruto > 0 && deducoes >= bruto;
  const contatoOk = nome.trim().length > 1 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && telefone.replace(/\D/g, "").length >= 10;

  useEffect(() => {
    setPraca(null);
    setSafras([]);
    if (esfera !== "federal" && uf.length !== 2) return;
    let vivo = true;
    safrasDaPraca({ esfera, uf })
      .then((r) => {
        if (!vivo) return;
        setPraca(r.praca);
        setSafras(r.safras);
        setAtivos(r.ativos);
        setSafra((cur) => (r.safras.includes(cur) ? cur : r.safras[0] ?? ""));
      })
      .catch((e) => vivo && setErro(e.message));
    return () => { vivo = false; };
  }, [esfera, uf]);

  async function calcular() {
    setErro(null);
    if (!contatoOk) return setErro("Preencha nome, e-mail e telefone para continuar.");
    if (bruto <= 0) return setErro("Informe ao menos o valor principal do precatório.");
    if (deducoesExcedem) {
      return setErro(
        `As deduções somam ${formatBRL(deducoes)} e superam o valor atualizado de ${formatBRL(bruto)}. ` +
          "Confira honorários, IR, PSS, parcela preferencial e outras despesas antes de continuar."
      );
    }
    setCarregando(true);
    try {
      const p = await calcularPrecatorio({
        nome: nome.trim(), email: email.trim(), telefone, processo: processo || null,
        esfera, uf: uf || null, municipio: municipio || null, safra, ativo: ativo || null, natureza,
        principal: num(v.principal), juros: num(v.juros), selic: num(v.selic),
        honorarios_pct: Number(honorarios.replace(",", ".")) || 0,
        ir_pct: Number(ir.replace(",", ".")) || 0,
        ir_base: irBase,
        pss: num(v.pss), preferencia: num(v.preferencia), outras_despesas: num(v.outras),
      });
      setPendente(p);
      setEtapa("codigo");
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (e: any) {
      setErro(e.message);
    } finally {
      setCarregando(false);
    }
  }

  return (
    <main className="min-h-screen bg-secondary/40 px-4 py-8 sm:py-12">
      <div className="mx-auto w-full max-w-3xl space-y-6">
        <header className="space-y-2 text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/precatur-logo.png" alt="Precatur" className="mx-auto h-12 w-auto object-contain" />
          <h1 className="flex items-center justify-center gap-2 text-2xl font-semibold tracking-tight">
            <Calculator className="h-6 w-6" />
            Simule quanto vale seu precatório
          </h1>
          <p className="text-sm text-muted-foreground">
            Preencha os dados da sua conta de liquidação e veja quanto a Precatur pagaria hoje.
          </p>
        </header>

        {etapa === "form" ? (
          <section className="space-y-5 rounded-lg border bg-card p-5 shadow-sm sm:p-8">
            <Passo n={1} titulo="Seus dados" />
            <div className="grid gap-4 sm:grid-cols-2">
              <Campo label="Nome ou escritório">
                <input className={inputClass} value={nome} maxLength={160} onChange={(e) => setNome(e.target.value)} />
              </Campo>
              <Campo label="E-mail">
                <input type="email" className={inputClass} value={email} maxLength={160} onChange={(e) => setEmail(e.target.value)} />
              </Campo>
              <Campo label="Telefone / WhatsApp">
                <input className={inputClass} inputMode="tel" value={telefone} placeholder="(27) 99999-0000"
                  onChange={(e) => setTelefone(maskTelefone(e.target.value))} />
                <span className="block text-xs text-muted-foreground">
                  Enviaremos um código por WhatsApp para confirmar o número.
                </span>
              </Campo>
              <Campo label="Número do processo (opcional)">
                <input className={inputClass} inputMode="numeric" value={processo} placeholder="0000000-00.0000.0.00.0000"
                  onChange={(e) => setProcesso(maskProcesso(e.target.value))} />
              </Campo>
            </div>

            <hr />
            <Passo n={2} titulo="Onde está o precatório" />
            <div className="flex flex-wrap gap-2">
              {(["federal", "estadual", "municipal"] as const).map((e) => (
                <button key={e} onClick={() => setEsfera(e)}
                  className={`rounded-md border px-3 py-1.5 text-sm font-medium capitalize transition-colors ${
                    esfera === e ? "border-primary bg-primary text-primary-foreground" : "hover:bg-accent"}`}>
                  {e}
                </button>
              ))}
            </div>
            {esfera !== "federal" ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <Campo label="Estado (UF)">
                  <select className={inputClass} value={uf} onChange={(e) => setUf(e.target.value)}>
                    <option value="">Selecione…</option>
                    {UFS.map((u) => <option key={u} value={u}>{u}</option>)}
                  </select>
                </Campo>
                {esfera === "municipal" ? (
                  <Campo label="Município">
                    <input className={inputClass} value={municipio} maxLength={120}
                      onChange={(e) => setMunicipio(e.target.value)} placeholder="Ex.: Sorocaba" />
                  </Campo>
                ) : null}
              </div>
            ) : null}
            {praca ? (
              <>
                <div className="grid gap-4 sm:grid-cols-3">
                  <Campo label="Ano previsto de pagamento">
                    <select className={inputClass} value={safra} onChange={(e) => setSafra(e.target.value)}>
                      {safras.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  </Campo>
                  <Campo label="Natureza">
                    <select className={inputClass} value={natureza} onChange={(e) => setNatureza(e.target.value as any)}>
                      <option value="alimentar">Alimentar</option>
                      <option value="comum">Comum</option>
                    </select>
                  </Campo>
                  {ativos.length > 1 ? (
                    <Campo label="Tipo de ativo">
                      <select className={inputClass} value={ativo} onChange={(e) => setAtivo(e.target.value)}>
                        <option value="">Automático</option>
                        {ativos.map((a) => <option key={a} value={a}>{a}</option>)}
                      </select>
                    </Campo>
                  ) : null}
                </div>
                {praca.estimativa ? (
                  <Aviso>
                    Ainda não temos tabela específica para essa praça; usamos a referência do{" "}
                    <strong>{praca.label}</strong> e o valor sai como <strong>estimativa</strong>.
                  </Aviso>
                ) : null}
              </>
            ) : null}

            <hr />
            <Passo n={3} titulo="Valores da conta de liquidação" />
            <div className="grid gap-4 sm:grid-cols-3">
              <Dinheiro label="Valor principal" valor={v.principal} onChange={(x) => setV({ ...v, principal: x })} />
              <Dinheiro label="Valor dos juros" valor={v.juros} onChange={(x) => setV({ ...v, juros: x })} />
              <Dinheiro label="SELIC" valor={v.selic} onChange={(x) => setV({ ...v, selic: x })}
                dica="Valor da atualização que consta na conta do tribunal" />
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <Campo label="Honorários do advogado (%)">
                <input className={inputClass} inputMode="decimal" value={honorarios} onChange={(e) => setHonorarios(e.target.value)} />
              </Campo>
              <Campo label="Imposto de renda (%)">
                <input className={inputClass} inputMode="decimal" value={ir} onChange={(e) => setIr(e.target.value)} />
              </Campo>
              <Campo label="IR incide sobre">
                <select className={inputClass} value={irBase} onChange={(e) => setIrBase(e.target.value as any)}>
                  <option value="principal">Principal</option>
                  <option value="bruto">Valor atualizado</option>
                </select>
              </Campo>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <Dinheiro label="PSS" valor={v.pss} onChange={(x) => setV({ ...v, pss: x })} />
              <Dinheiro label="Parcela preferencial" valor={v.preferencia} onChange={(x) => setV({ ...v, preferencia: x })} />
              <Dinheiro label="Outras despesas" valor={v.outras} onChange={(x) => setV({ ...v, outras: x })} />
            </div>

            {bruto > 0 ? (
              <p className="rounded-md bg-secondary px-3 py-2 text-sm">
                Valor bruto atualizado: <strong>{formatBRL(bruto)}</strong>
                {deducoes > 0 ? <> · deduções: <strong>{formatBRL(deducoes)}</strong></> : null}
              </p>
            ) : null}
            {deducoesExcedem ? (
              <Aviso>
                As deduções informadas <strong>superam o valor atualizado</strong>. Do jeito que está, o
                líquido seria zero e não haveria o que comprar — confira honorários, IR, PSS, parcela
                preferencial e outras despesas.
              </Aviso>
            ) : null}
            {erro ? <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{erro}</p> : null}

            <Button className="w-full gap-2" onClick={calcular} disabled={carregando || !praca || !safra || deducoesExcedem}>
              {carregando ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4" />}
              {carregando ? "Enviando código…" : "Calcular quanto receberia"}
            </Button>
            <p className="text-center text-xs text-muted-foreground">
              Para ver o valor, confirmamos seu WhatsApp com um código de 6 dígitos.
            </p>
          </section>
        ) : null}

        {etapa === "codigo" && pendente ? (
          <Verificacao
            pendente={pendente}
            onVerificado={(r) => {
              setResultado(r);
              setEtapa("resultado");
              window.scrollTo({ top: 0, behavior: "smooth" });
            }}
            onCorrigir={() => {
              setEtapa("form");
              setPendente(null);
            }}
          />
        ) : null}

        {etapa === "resultado" && resultado ? <Resultado r={resultado} /> : null}

        <p className="text-center text-xs text-muted-foreground">
          Simulação sem compromisso. O valor final depende da análise dos documentos do precatório.
        </p>
      </div>
    </main>
  );
}

function Verificacao({ pendente, onVerificado, onCorrigir }: {
  pendente: CalculoPendente;
  onVerificado: (r: CalculoResposta) => void;
  onCorrigir: () => void;
}) {
  const [codigo, setCodigo] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(false);
  const [espera, setEspera] = useState(60);
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => { ref.current?.focus(); }, []);
  useEffect(() => {
    if (espera <= 0) return;
    const t = setTimeout(() => setEspera((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [espera]);

  async function confirmar(e: React.FormEvent) {
    e.preventDefault();
    setErro(null);
    setCarregando(true);
    try {
      onVerificado(await verificarCodigo(pendente.id, codigo));
    } catch (e: any) {
      setErro(e.message);
      setCodigo("");
      ref.current?.focus();
    } finally {
      setCarregando(false);
    }
  }

  async function reenviar() {
    setErro(null);
    setAviso(null);
    try {
      await reenviarCodigo(pendente.id);
      setAviso("Enviamos um novo código.");
      setEspera(60);
    } catch (e: any) {
      setErro(e.message);
    }
  }

  return (
    <section className="space-y-5 rounded-lg border bg-card p-5 text-center shadow-sm sm:p-8">
      <MessageCircle className="mx-auto h-10 w-10 text-emerald-600" />
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Confirme seu WhatsApp</h2>
        <p className="text-sm text-muted-foreground">
          Enviamos um código de 6 dígitos para <strong>{pendente.verificacao.telefone}</strong>.
          Informe-o para ver quanto pagaríamos.
        </p>
      </div>

      <form onSubmit={confirmar} className="space-y-4">
        <input ref={ref} value={codigo} inputMode="numeric" autoComplete="one-time-code" maxLength={6}
          onChange={(e) => setCodigo(e.target.value.replace(/\D/g, "").slice(0, 6))}
          placeholder="000000"
          className="mx-auto block h-14 w-48 rounded-md border border-input bg-background text-center text-2xl font-semibold tracking-[0.4em] shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
        {erro ? <p className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{erro}</p> : null}
        {aviso ? <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{aviso}</p> : null}
        <Button type="submit" className="w-full gap-2" disabled={carregando || codigo.length !== 6}>
          {carregando ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
          {carregando ? "Conferindo…" : "Ver meu valor"}
        </Button>
      </form>

      <div className="flex flex-wrap justify-center gap-3 text-xs text-muted-foreground">
        <button onClick={reenviar} disabled={espera > 0} className="underline disabled:no-underline disabled:opacity-60">
          {espera > 0 ? `Reenviar código em ${espera}s` : "Reenviar código"}
        </button>
        <button onClick={onCorrigir} className="underline">Corrigir meus dados</button>
      </div>
    </section>
  );
}

function Resultado({ r }: { r: CalculoResposta }) {
  return (
    <section className="space-y-5 rounded-lg border bg-card p-5 shadow-sm sm:p-8">
      <Passo n={4} titulo="Resultado da simulação" />
      <dl className="space-y-1.5 text-sm">
        <Linha k="Valor bruto atualizado" v={formatBRL(r.bruto)} />
        <Linha k="Honorários do advogado" v={`− ${formatBRL(r.honorarios)}`} />
        <Linha k="Imposto de renda" v={`− ${formatBRL(r.ir)}`} />
        {r.pss ? <Linha k="PSS" v={`− ${formatBRL(r.pss)}`} /> : null}
        {r.preferencia ? <Linha k="Parcela preferencial" v={`− ${formatBRL(r.preferencia)}`} /> : null}
        {r.outras_despesas ? <Linha k="Outras despesas" v={`− ${formatBRL(r.outras_despesas)}`} /> : null}
        <div className="flex justify-between border-t pt-2 font-semibold">
          <dt>Valor líquido a receber</dt>
          <dd className="tabular-nums">{formatBRL(r.liquido)}</dd>
        </div>
      </dl>

      {r.liquido <= 0 ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-5 text-amber-900">
          <div className="text-sm font-semibold">As deduções consumiram todo o valor</div>
          <p className="mt-1 text-sm">
            Somadas, as deduções informadas alcançam o valor atualizado de {formatBRL(r.bruto)}, então não
            resta valor líquido a comprar. Confira os campos de honorários, IR, PSS, parcela preferencial e
            outras despesas — um deles costuma estar com uma casa decimal a mais.
          </p>
        </div>
      ) : (
        <div className="rounded-lg bg-primary p-5 text-primary-foreground">
          <div className="text-xs font-medium uppercase tracking-wider opacity-80">A Precatur pagaria hoje</div>
          <div className="mt-1 text-3xl font-bold tabular-nums sm:text-4xl">{formatBRL(r.proposta)}</div>
          <div className="mt-1 text-xs opacity-80">
            {r.percentual}% do valor líquido · safra {r.safra} · {r.ativo}
            {r.abatimento ? ` · abatimento de ${formatBRL(r.abatimento)}` : ""}
          </div>
        </div>
      )}

      {r.praca.estimativa ? (
        <Aviso>
          Valor <strong>estimado</strong>: ainda não há tabela específica para essa praça, então usamos a
          referência do {r.praca.label}. Nossa equipe confirma após analisar os documentos.
        </Aviso>
      ) : null}

      <p className="flex items-start gap-2 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
        <ShieldCheck className="mt-0.5 h-4 w-4 flex-shrink-0" />
        <span>
          WhatsApp confirmado. Nossa equipe já recebeu sua simulação e entra em contato para formalizar a
          proposta.
        </span>
      </p>
    </section>
  );
}

function Passo({ n, titulo }: { n: number; titulo: string }) {
  return (
    <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-xs text-primary-foreground">{n}</span>
      {titulo}
    </h2>
  );
}

function Campo({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}

function Dinheiro({ label, valor, onChange, dica }: {
  label: string; valor: string; onChange: (v: string) => void; dica?: string;
}) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium">{label}</span>
      <div className="flex h-10 items-center rounded-md border border-input bg-background px-3 shadow-sm focus-within:ring-2 focus-within:ring-ring">
        <span className="text-muted-foreground">R$</span>
        <input value={valor} inputMode="decimal" className="h-full w-full bg-transparent px-2 text-sm outline-none"
          onChange={(e) => onChange(maskMoeda(e.target.value))}
          onBlur={() => onChange(fechaMoeda(valor))} />
      </div>
      {dica ? <span className="block text-xs text-muted-foreground">{dica}</span> : null}
    </label>
  );
}

function Aviso({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-start gap-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
      <Info className="mt-0.5 h-4 w-4 flex-shrink-0" />
      <span>{children}</span>
    </p>
  );
}

function Linha({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="tabular-nums">{v}</dd>
    </div>
  );
}
