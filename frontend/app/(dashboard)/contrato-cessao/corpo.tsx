// Texto do Instrumento Preliminar de Cessão Onerosa de Direitos Creditórios.
//
// Veio do "CONTRATO MODELO" do comercial (25/11/2026) e passou a ser a fonte:
// quando o jurídico mudar uma cláusula, muda-se aqui. As partes que eram em
// vermelho no .docx são campos (V, Din, Ext, Pct) e tudo que concorda com o
// gênero do cedente vem de `c` (ver formasDoCedente), de modo que uma chave
// troca todas as ocorrências de uma vez.
//
// O foro é sempre a Comarca de Vitória/ES (confirmado com o comercial).

import type { DadosContrato, Derivados, Formas } from "@/lib/contrato-cessao";
import { Din, Ext, Pct, V } from "./campos";

export function Corpo({
  d,
  c,
  x,
  dataExt,
  anoPadrao,
}: {
  d: DadosContrato;
  c: Formas;
  x: Derivados;
  dataExt: string | null;
  anoPadrao: number;
}) {
  return (
    <>
        <p className="contrato-titulo sp">
          INSTRUMENTO PRELIMINAR DE CESSÃO ONEROSA DE DIREITOS CREDITÓRIOS
        </p>
        <p className="sp">
          <strong>
            CEDENTE: <V v={d.cedenteNome} w={18} />
          </strong>
          {d.tipo === "pj" ? (
            <>
              , pessoa jurídica de direito privado, inscrita no CNPJ/MF sob nº{" "}
              <strong>
                <V v={d.cedenteDoc} w={10} />
              </strong>
              , com sede situada em <V v={d.cedenteEndereco} w={22} />, neste ato
              representada por seu sócio-administrador, na forma de seus atos
              constitutivos
            </>
          ) : (
            <>
              , <V v={d.nacionalidade} w={7} />, <V v={d.estadoCivil} w={6} />,
              inscrit{c.a} no CPF sob nº{" "}
              <strong>
                <V v={d.cedenteDoc} w={9} />
              </strong>
              , residente e domiciliad{c.a} em{" "}
              <V v={d.cedenteEndereco} w={22} />
            </>
          )}
          , doravante denominad{c.a} simplesmente CEDENTE;
        </p>
        <p className="sp">
          <strong>
            CESSIONÁRIA: <V v={d.cessNome} w={18} />,
          </strong>{" "}
          pessoa jurídica de direito privado, inscrita no CNPJ sob nº{" "}
          <V v={d.cessCnpj} w={10} />, com sede na{" "}
          <V v={d.cessEndereco} w={22} />, neste ato representada por seu sócio
          administrador{" "}
          <strong>
            <V v={d.cessRepresentante} w={14} />,
          </strong>{" "}
          nos termos do contrato social.
        </p>
        <p className="sp">As partes, acima qualificadas, ajustam e contratam o presente Instrumento Preliminar de Cessão Onerosa de Direitos Creditórios e outras avenças, por meio do qual estabelecem os termos e condições em que pretendem, mediante a celebração de contrato definitivo, formalizar a cessão onerosa do crédito adiante descrito, em conformidade com as cláusulas e condições a seguir convencionadas.</p>
        <p className="contrato-clausula"><strong>CLÁUSULA PRIMEIRA – DO OBJETO</strong></p>
        <p className="sp"><strong>1.1. </strong>O presente instrumento tem por objeto estabelecer os termos e condições em que {c.a} <strong>CEDENTE</strong> e a <strong>CESSIONÁRIA</strong> pretendem celebrar, mediante a assinatura de contrato definitivo, a cessão onerosa, {c.pela} <strong>CEDENTE</strong> à <strong>CESSIONÁRIA</strong>, da integralidade do crédito de titularidade {c.da} <strong>CEDENTE</strong>, discriminados no Ofício Requisitório nº <V v={d.oficio} w={12} />, expedido pelo <V v={d.tribunal} w={16} /> e vinculado ao processo de origem nº <V v={d.processo} w={12} />, da <V v={d.vara} w={12} />.</p>
        <p className="sp"><strong>1.2. </strong>O crédito objeto da pretendida cessão corresponde ao valor de <Din n={x.liquido} /> (<Ext n={x.liquido} />), conforme consta do referido requisitório, referente {d.natureza === "honorarios" ? "aos honorários contratuais devidos" : "ao crédito principal devido"} {c.aa} <strong>CEDENTE</strong>.</p>
        <p className="sp"><strong>1.3. </strong>A pretendida cessão compreenderá <Pct t={x.percentual} /> do crédito pertencente {c.aa} <strong>CEDENTE</strong>, bem como todos os seus acessórios, inclusive atualização monetária, juros e demais acréscimos que lhe sejam legalmente atribuídos.</p>
        <p className="sp"><strong>1.4. </strong>Integrarão o objeto da cessão, uma vez celebrado o contrato definitivo, todos os direitos, ações, vantagens e prerrogativas inerentes ao crédito, inclusive aqueles necessários à sua cobrança, habilitação, recebimento e disposição.</p>
        <p className="contrato-clausula"><strong>CLÁUSULA SEGUNDA – DO PREÇO</strong></p>
        <p className="sp"><strong>2.1. </strong>Caso venha a ser celebrado o contrato definitivo, a <strong>CESSIONÁRIA</strong> pagará {c.aa} <strong>CEDENTE</strong>, pela aquisição da integralidade do crédito objeto deste instrumento, o preço correspondente a <strong><Din n={x.preco} /></strong> (<Ext n={x.preco} />).</p>
        <p className="sp"><strong>2.2. </strong>Após a conclusão da due diligence, a <strong>CESSIONÁRIA</strong> poderá, a seu exclusivo critério, estabelecer ou apresentar valor diverso, considerando o valor efetivamente disponível do crédito, sua titularidade, liquidez, exigibilidade, eventuais ônus, gravames, retenções, bloqueios, controvérsias e demais circunstâncias relevantes identificadas na análise. Nessa hipótese, a <strong>CESSIONÁRIA</strong> poderá optar por não celebrar o contrato definitivo, na forma do item 3.3, alínea “b”.</p>
        <p className="sp"><strong>2.3. </strong>A celebração do contrato definitivo e o pagamento integral do preço deverão ocorrer dentro do mesmo prazo de <strong>15 (quinze) dias úteis</strong> referido no item 3.1, observadas as etapas previstas na Cláusula Terceira.</p>
        <p className="contrato-clausula"><strong>CLÁUSULA TERCEIRA – DA DUE DILIGENCE</strong></p>
        <p className="sp"><strong>3.1. </strong>A <strong>CESSIONÁRIA</strong> terá o prazo de <strong>15 (quinze) dias úteis</strong>, contado da assinatura deste instrumento, para realizar, por si ou por terceiros por ela indicados, a due diligence jurídica, documental, processual e financeira que entender necessária à aquisição do crédito descrito na Cláusula Primeira (“Due Diligence”), prazo dentro do qual deverão ocorrer, também, a confirmação de interesse, a celebração do contrato definitivo e o pagamento do preço, nos termos do item 2.3.</p>
        <p className="sp"><strong>3.2. </strong>Para a realização da Due Diligence e a conclusão da operação, é necessária a documentação e as informações necessárias para avaliação da disponibilidade e liquidez do crédito.</p>
        <p className="sp">{c.A} <strong>CEDENTE</strong> compromete-se a colaborar com a <strong>CESSIONÁRIA</strong>, fornecendo, no prazo por esta assinalado, a documentação e as informações que dependam de sua atuação direta.</p>
        <p><strong>3.3. </strong>Concluída a Due Diligence dentro do prazo previsto no item 3.1, a <strong>CESSIONÁRIA</strong> poderá, ainda dentro desse mesmo prazo:</p>
        <p>a) confirmar seu interesse na aquisição do crédito, hipótese em que as partes se obrigam a celebrar o contrato definitivo de cessão onerosa de direitos creditórios, nos termos e condições ora acordados, dentro do prazo previsto no item 3.1; ou</p>
        <p className="sp">b) declinar da aquisição, mediante comunicação dirigida {c.aa} <strong>CEDENTE</strong>, hipótese em que o presente instrumento restará automaticamente resolvido, <strong>sem que seja devida, indenização, multa ou penalidade de qualquer natureza.</strong></p>
        <p className="sp"><strong>3.4. </strong>O decurso do prazo previsto no item 3.1 sem manifestação expressa da <strong>CESSIONÁRIA</strong> equivalerá à desistência da aquisição do crédito, aplicando-se os mesmos efeitos previstos no item 3.3, alínea “b”.</p>
        <p className="contrato-clausula"><strong>CLÁUSULA QUARTA – DA EXCLUSIVIDADE DE NEGOCIAÇÃO</strong></p>
        <p className="sp"><strong>4.1. </strong>A exclusividade ora pactuada terá início na data de assinatura deste instrumento e vigorará pelo prazo de <strong>15 (quinze) dias úteis</strong>, correspondente ao prazo de vigência deste instrumento, durante o qual {c.a} <strong>CEDENTE</strong> obriga-se a negociar <strong>exclusivamente</strong> com a <strong>CESSIONÁRIA</strong> a cessão do crédito descrito na Cláusula Primeira.</p>
        <p className="sp"><strong>4.2. </strong>Durante o período de exclusividade referido no item 4.1, {c.a} <strong>CEDENTE</strong> compromete-se a não oferecer, negociar, ceder, prometer ceder, onerar, transferir ou por qualquer forma dispor, direta ou indiretamente, no todo ou em parte, do crédito objeto deste instrumento a terceiros, bem como a não manter, iniciar ou dar continuidade a negociações, tratativas ou contatos com terceiros que tenham por objeto, direto ou indireto, o mesmo crédito.</p>
        <p className="sp"><strong>4.3. </strong>O descumprimento, {c.pela} <strong>CEDENTE</strong>, da obrigação de exclusividade prevista nesta Cláusula sujeitará {c.infrator} ao pagamento, em favor da <strong>CESSIONÁRIA</strong>, de <strong>multa correspondente a 5% (cinco por cento) do valor do crédito</strong> indicado no item 1.2 deste instrumento — o que corresponde, nesta data, a <strong><Din n={x.multa} /></strong> (<Ext n={x.multa} />) —, sem prejuízo alternativamente do direito da <strong>CESSIONÁRIA</strong> de exigir o cumprimento específico da obrigação, quando cabível, e de pleitear as perdas e danos comprovados que excedam o valor da multa.</p>
        <p className="sp"><strong>4.4. </strong>A obrigação de exclusividade prevista nesta Cláusula cessa antecipadamente caso a <strong>CESSIONÁRIA</strong> decline da aquisição do crédito nos termos do item 3.3, alínea “b”, ou não se manifeste no prazo do item 3.1, aplicando-se o disposto no item 3.4, casos em que {c.a} <strong>CEDENTE</strong> recupera plena liberdade de negociação a partir da respectiva data, ainda que anterior ao termo de 15 (quinze) dias úteis previsto no item 4.1.</p>
        <p className="contrato-clausula"><strong>CLÁUSULA QUINTA – DA NATUREZA JURÍDICA E DA CELEBRAÇÃO DO CONTRATO DEFINITIVO</strong></p>
        <p className="sp"><strong>5.1. </strong>As partes reconhecem que o presente instrumento possui natureza preliminar e condicionada, nos termos dos artigos 462 a 466 do Código Civil, destinando-se a estabelecer as bases da eventual cessão onerosa dos direitos creditórios descritos na Cláusula Primeira. Este instrumento não transfere a titularidade do crédito nem obriga a <strong>CESSIONÁRIA</strong> a celebrar o contrato definitivo, ficando a conclusão da operação condicionada à aprovação expressa da <strong>CESSIONÁRIA</strong>, ao cumprimento das condições precedentes, à aceitação do preço final e à assinatura do instrumento definitivo de cessão onerosa de direitos creditórios.</p>
        <p className="sp"><strong>5.2. </strong>O contrato definitivo reproduzirá, no que for aplicável, os termos e condições estabelecidos neste instrumento, o preço da cessão, contudo, será definitivo após a conclusão da Due Diligence, podendo ser diverso do valor inicialmente indicado no item 2.1, conforme os elementos apurados na análise do crédito.</p>
        <p className="sp"><strong>5.3. </strong>Este instrumento não confere à <strong>CESSIONÁRIA</strong> qualquer direito de habilitação, anotação ou levantamento do crédito perante o <V v={d.tribunal} w={16} />, o juízo de origem ou o ente devedor, direitos que somente poderão ser exercidos após a celebração do contrato definitivo.</p>
        <p className="contrato-clausula"><strong>CLÁUSULA SEXTA – DAS DECLARAÇÕES E GARANTIAS {c.DA} CEDENTE</strong></p>
        <p><strong>6.1. </strong>{c.A} <strong>CEDENTE</strong> declara e garante, desde já, para fins de subsidiar a Due Diligence e a eventual celebração do contrato definitivo:</p>
        <p>a) ser {c.legitimo} titular do crédito objeto deste instrumento;</p>
        <p>b) que o crédito se encontra regularmente destacado e individualizado no requisitório referido neste instrumento;</p>
        <p>c) que o crédito está livre e desembaraçado de quaisquer ônus, gravames, penhoras, bloqueios, cessões anteriores, promessas de cessão, compensações ou quaisquer outros direitos de terceiros;</p>
        <p>d) que não celebrou qualquer negócio jurídico anterior incompatível com a pretendida cessão;</p>
        <p>e) que não figura no polo passivo de qualquer ação judicial ou execução cuja existência, considerando sua natureza e eventual impacto patrimonial, seja capaz de conduzi-la ou contribuir para sua insolvência, tampouco possui conhecimento de qualquer circunstância dessa natureza que possa comprometer a validade, eficácia ou disponibilidade do crédito objeto deste instrumento;</p>
        <p>f) que a pretendida cessão não é realizada com o propósito de fraudar, prejudicar ou frustrar direitos de terceiros, nem resulta de qualquer negócio simulado ou destinado à ocultação ou dilapidação de seu patrimônio;</p>
        <p>g) que não tem conhecimento de controvérsia, impugnação ou discussão capaz de comprometer a existência, titularidade ou disponibilidade do crédito;</p>
        <p>h) que possui plena capacidade e poderes para celebrar este instrumento e, oportunamente, o contrato definitivo; e</p>
        <p className="sp">i) que fornecerá à <strong>CESSIONÁRIA</strong>, no âmbito da Due Diligence, todos os documentos necessários à comprovação da titularidade e regularidade do crédito.</p>
        <p className="sp"><strong>6.2. </strong>{c.A}<strong> CEDENTE </strong>responderá integralmente por qualquer prejuízo decorrente de falsidade, omissão, duplicidade de cessão ou ilegitimidade da operação.</p>
        <p className="contrato-clausula"><strong>CLÁUSULA SÉTIMA – DA CONFIDENCIALIDADE E DA LGPD</strong></p>
        <p className="sp"><strong>7.1. </strong>As partes comprometem-se a manter sigilo sobre as informações, documentos, condições comerciais e demais dados a que tenham acesso em razão da Due Diligence e das negociações objeto deste instrumento, ressalvadas as hipóteses de divulgação exigidas por lei, ordem judicial ou autoridade competente.</p>
        <p className="sp"><strong>7.2. </strong>As partes comprometem-se a observar a legislação aplicável à proteção de dados pessoais, especialmente a Lei nº 13.709/2018 – Lei Geral de Proteção de Dados Pessoais (LGPD).</p>
        <p className="contrato-clausula"><strong>CLÁUSULA OITAVA – DA RESOLUÇÃO</strong></p>
        <p><strong>8.1. </strong>O presente instrumento poderá ser resolvido de pleno direito, independentemente de interpelação ou notificação judicial ou extrajudicial: </p>
        <p>(i) nas hipóteses previstas na Cláusula Terceira, itens 3.3, alínea “b”, e 3.4, <strong>sem que seja devida, nesses casos, qualquer multa, penalidade ou indenização entre as partes</strong>; </p>
        <p>(ii) na hipótese de descumprimento, por qualquer das partes, de obrigação essencial aqui prevista, nos termos do artigo 474 do Código Civil.</p>
        <p>(iii) {c.a} <strong>CEDENTE</strong> não apresentar os documentos solicitados;</p>
        <p>(iv) forem constatadas inconsistências, ônus, restrições ou riscos não informados;</p>
        <p>(v) houver alteração relevante no valor, na titularidade, na ordem ou na situação do precatório;</p>
        <p className="sp">(vi) a <strong>CESSIONÁRIA</strong>, após a análise jurídica, documental, econômica ou operacional, concluir pela sua inviabilidade ou inadequação.</p>
        <p className="sp"><strong>8.2. </strong>Configurada a resolução por descumprimento culposo de obrigação essencial, a parte infratora responderá pelas perdas e danos comprovadamente sofridos pela outra parte, sem prejuízo da multa especificamente prevista na Cláusula Quarta para o descumprimento da obrigação de exclusividade.</p>
        <p className="sp"><strong>8.3. </strong>Caso, por qualquer motivo, seja devida a restituição de valores eventualmente pagos por uma parte à outra no âmbito deste instrumento, tais valores serão restituídos corrigidos exclusivamente pela <strong>taxa SELIC, pro rata die</strong>, calculada entre a data do respectivo pagamento e a data da efetiva restituição, sem cumulação com qualquer outro índice de correção monetária ou taxa de juros.</p>
        <p className="contrato-clausula"><strong>CLÁUSULA NONA – DO TÍTULO EXECUTIVO EXTRAJUDICIAL</strong></p>
        <p className="sp"><strong>9.1. </strong>O presente instrumento, assinado pelas partes e por 2 (duas) testemunhas, constitui título executivo extrajudicial, nos termos do artigo 784, III, do Código de Processo Civil, relativamente às obrigações líquidas, certas e exigíveis nele previstas, inclusive a multa estabelecida na Cláusula Quarta.</p>
        <p className="sp"><strong>9.2. </strong>O descumprimento de qualquer obrigação assumida neste instrumento poderá ensejar a adoção das medidas judiciais cabíveis, sem prejuízo das demais consequências previstas em lei ou neste contrato.</p>
        <p className="contrato-clausula"><strong>CLÁUSULA DÉCIMA – DISPOSIÇÕES GERAIS</strong></p>
        <p className="sp"><strong>10.1. </strong>O presente instrumento obriga as partes e seus sucessores a qualquer título.</p>
        <p className="sp"><strong>10.2. </strong>A eventual tolerância de qualquer das partes quanto ao descumprimento de obrigação aqui prevista não constituirá renúncia, novação ou alteração das disposições deste instrumento.</p>
        <p className="sp"><strong>10.3. </strong>Caso qualquer disposição deste instrumento seja considerada inválida, nula ou inexequível, as demais permanecerão válidas e eficazes.</p>
        <p className="sp"><strong>10.4. </strong>O presente instrumento representa a integralidade do acordo celebrado entre as partes relativamente à preliminar cessão do crédito nele descrito, substituindo quaisquer entendimentos, tratativas ou documentos anteriores sobre o mesmo objeto.</p>
        <p className="sp"><strong>10.5.</strong> As <strong>PARTES</strong> poderão assinar este instrumento física ou eletronicamente, reconhecendo a validade, autenticidade e integridade das assinaturas utilizadas.</p>
        <p className="sp"><strong>10.6. </strong>Este instrumento possui natureza autônoma e independente em relação a quaisquer outros instrumentos de igual natureza eventualmente celebrados pela <strong>CESSIONÁRIA</strong> com outros titulares de créditos decorrentes do mesmo requisitório, não estando sua validade, eficácia ou exigibilidade condicionadas à celebração ou ao cumprimento de quaisquer desses outros instrumentos.</p>
        <p className="contrato-clausula"><strong>CLÁUSULA DÉCIMA PRIMEIRA – DO FORO</strong></p>
        <p className="sp"><strong>11.1. </strong>Fica eleito o foro da Comarca de Vitória, Estado do Espírito Santo, para dirimir quaisquer controvérsias decorrentes deste instrumento, com renúncia a qualquer outro, por mais privilegiado que seja.</p>

        <div className="contrato-final">
          <p className="sp">E, por estarem justas e contratadas, as partes assinam o presente instrumento, juntamente com 2 (duas) testemunhas, para todos os fins de direito.</p>
          <p className="contrato-data sp">
            <V v={d.local} w={10} />,{" "}
            {dataExt ?? (
              <>
                <span className="contrato-linha" style={{ width: "2em" }} /> de{" "}
                <span className="contrato-linha" style={{ width: "7em" }} /> de {anoPadrao}
              </>
            )}
            .
          </p>

          <div className="contrato-assinaturas">
            <div>
              <div className="contrato-assinatura-linha" />
              <div>{d.cedenteNome.trim() || " "}</div>
              <strong>Cedente</strong>
            </div>
            <div>
              <div className="contrato-assinatura-linha" />
              <div>
                <strong>{d.cessNome.trim() || " "}</strong>
              </div>
              <strong>Cessionária</strong>
            </div>
          </div>

          <p className="contrato-testemunhas">
            <strong>Testemunhas:</strong>
          </p>
          <div className="contrato-assinaturas contrato-testemunhas-linhas">
            {[0, 1].map((k) => (
              <div key={k}>
                <div className="contrato-assinatura-linha" />
                <div className="contrato-esq">Nome:</div>
                <div className="contrato-esq">CPF:</div>
              </div>
            ))}
          </div>
        </div>

    </>
  );
}
