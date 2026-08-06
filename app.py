# Interface do Botão de Execução
if st.button("🚀 Processar Dinamicamente com IA e Gerar PDFs", type="primary"):
    if not api_key:
        st.error("⚠️ Insira sua chave da API do Google GenAI.")
    elif pdf_original and pdf_alteradora:
        with st.spinner("Lendo os PDFs, cruzando os atos e estruturando os dados dinamicamente..."):
            try:
                texto_orig = extrair_texto_de_upload(pdf_original)
                texto_alt = extrair_texto_de_upload(pdf_alteradora)
                
                # Chamada estruturada ao Gemini (garantindo que a chave não tenha espaços invisíveis)
                chave_limpa = api_key.strip()
                dados_estruturados = analisar_normas_com_gemini_dinamico(texto_orig, texto_alt, chave_limpa)
                
                # Geração dos PDFs utilizando os dados reais processados pela IA
                pdf_alt_bytes = gerar_pdf_dinamico("VERSÃO ALTERADA - Dinâmica", dados_estruturados, "alterada")
                pdf_cons_bytes = gerar_pdf_dinamico("VERSÃO CONSOLIDADA - Dinâmica", dados_estruturados, "consolidada")
                
                st.success("✨ Processamento dinâmico concluído com sucesso!")
                st.divider()
                st.subheader("📥 Baixe os PDFs Oficiais Prontos:")
                
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.download_button(label="Baixar Versão Alterada (PDF)", data=pdf_alt_bytes, file_name="versao_alterada_dinamica.pdf", mime="application/pdf")
                with col_d2:
                    st.download_button(label="Baixar Versão Consolidada (PDF)", data=pdf_cons_bytes, file_name="versao_consolidada_dinamica.pdf", mime="application/pdf")
            
            except Exception as e:
                st.error("❌ Ocorreu um erro na comunicação com a Inteligência Artificial do Google.")
                st.warning("Verifique os detalhes do erro abaixo para entender o que deu errado:")
                st.code(str(e)) # Isso forçará o Streamlit a mostrar o erro real!
                
    else:
        st.warning("⚠️ Envie ambos os arquivos PDF para iniciar.")
