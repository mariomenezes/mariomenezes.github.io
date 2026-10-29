---
layout: default
---

## Posts em português

<ul class="post-list">
{% assign pt = site.posts | where: "lang", "pt-BR" %}
{% for post in pt %}
  <li>
    <span class="post-meta">{{ post.date | date: "%d/%m/%Y" }}</span>
    <h3><a class="post-link" href="{{ post.url | relative_url }}">{{ post.title | escape }}</a></h3>
  </li>
{% endfor %}
</ul>

## Posts in English

<ul class="post-list">
{% assign en = site.posts | where: "lang", "en" %}
{% for post in en %}
  <li>
    <span class="post-meta">{{ post.date | date: "%b %-d, %Y" }}</span>
    <h3><a class="post-link" href="{{ post.url | relative_url }}">{{ post.title | escape }}</a></h3>
  </li>
{% endfor %}
</ul>

<p class="rss-subscribe">RSS: <a href="{{ "/feed.xml" | relative_url }}">feed.xml</a></p>
