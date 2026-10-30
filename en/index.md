---
layout: default
lang: en
title: Lab notes
permalink: /en/
description: "Mario Menezes, platform and DevOps engineer: lab notes on Kubernetes, service mesh, AWS and AI in a homelab, with measurements and material to reproduce them."
image: /assets/img/perfil.jpg
---

<div class="home">
{% include perfil.html lang="en" %}
<section class="home-main">
  <h2 class="home-titulo">Lab notes</h2>
  <p class="home-intro">Each post measures something in a real environment (homelab or lab), shows the numbers with sample size and conditions, admits what went wrong and ships the material for you to repeat it.</p>
  <div class="home-cards">
    <a class="home-card" href="#posts"><strong>Posts</strong><span>{{ site.posts | where: "lang", "en" | size }} published</span></a>
    <a class="home-card" href="{{ "/en/about/" | relative_url }}"><strong>Résumé</strong><span>experience and certifications</span></a>
    <a class="home-card" href="https://www.linkedin.com/in/mario-a-menezes-costa/" rel="me noopener"><strong>LinkedIn</strong><span>let's connect</span></a>
    <a class="home-card" href="https://github.com/mariomenezes/mariomenezes.github.io/tree/main/labs" rel="noopener"><strong>Labs</strong><span>scripts and data behind the posts</span></a>
  </div>
  <h2 class="home-sec" id="posts">Recent posts</h2>
  {% include lista-posts.html lang="en" %}
</section>
</div>
