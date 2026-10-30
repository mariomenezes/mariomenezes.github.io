---
layout: default
lang: pt-BR
title: Notas de laboratório
description: "Mario Menezes, engenheiro de plataforma e DevOps: notas de laboratório sobre Kubernetes, service mesh, AWS e IA no homelab, com medições e material para reproduzir."
image: /assets/img/perfil.jpg
---

<div class="home">
{% include perfil.html lang="pt" %}
<section class="home-main">
  <h2 class="home-titulo">Notas de laboratório</h2>
  <p class="home-intro">Cada post mede algo num ambiente real (homelab ou laboratório), mostra os números com a amostra e as condições, admite o que deu errado e traz o material para você repetir.</p>
  <div class="home-cards">
    <a class="home-card" href="#posts"><strong>Posts</strong><span>{{ site.posts | where: "lang", "pt-BR" | size }} publicados</span></a>
    <a class="home-card" href="{{ "/sobre/" | relative_url }}"><strong>Currículo</strong><span>experiência e certificações</span></a>
    <a class="home-card" href="https://www.linkedin.com/in/mario-a-menezes-costa/" rel="me noopener"><strong>LinkedIn</strong><span>vamos conversar</span></a>
    <a class="home-card" href="https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs" rel="noopener"><strong>Labs</strong><span>scripts e dados dos posts</span></a>
  </div>
  <h2 class="home-sec" id="posts">Posts recentes</h2>
  {% include lista-posts.html lang="pt-BR" %}
</section>
</div>
