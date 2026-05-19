# JillyPickles context drift scenario

This directory contains a deliberately bad config generated from stale project
context. It disables pickle ordering and points the order route at an obsolete
cucumber cart path.

The demo scripts apply this config temporarily and restore the healthy config
before exiting.
