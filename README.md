# Daily log

Registro automatico diario executado pelo GitHub Actions. Os commits deste
repositorio sao gerados por automacao e nao representam desenvolvimento manual.

## Funcionamento

- Tentativas diarias as 06:17, 12:17 e 20:17, no fuso America/Bahia.
- No maximo um registro por dia; as tentativas posteriores nao fazem novo commit
  se o registro do dia ja existe.
- O arquivo daily-log.json guarda a data mais recente. O historico Git preserva
  os registros anteriores.
- Usa o GITHUB_TOKEN temporario do proprio repositorio, sem token pessoal.
- Pode ser iniciado manualmente em Actions > Daily automated log > Run workflow.
- Para interromper: Actions > Daily automated log > Disable workflow.

## Contribuicoes no perfil

O repositorio deve permanecer na conta Jhenrique00, com o workflow na branch
principal. O e-mail noreply de autoria corresponde a essa conta.
Como o repositorio e privado, habilite a exibicao de contribuicoes privadas
nas configuracoes de contribuicoes do perfil para mostrar as contagens.
Essa opcao tambem mostra contagens anonimas de outras contribuicoes privadas;
ela nao publica o conteudo deste repositorio.

Agendamentos do GitHub podem atrasar ou falhar, portanto nao ha garantia de
todos os dias verdes. As tres tentativas reduzem esse risco. Em repositorios
privados, as execucoes consomem a franquia de minutos do GitHub Actions.
Nenhuma data retroativa e criada.