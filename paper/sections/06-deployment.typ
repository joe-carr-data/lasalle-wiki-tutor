#import "../diagrams.typ": deployment, DARK, LIGHT

= Deployment and Availability

// Access token is injected at compile time via `--input access-token=...`.
// When absent (the public build), the box prints an out-of-band notice
// instead of the literal token, so the source-of-truth Typst file is safe
// to commit to a public repository.
#let access-token = sys.inputs.at("access-token", default: none)

#block(
  width: 100%,
  fill: LIGHT,
  stroke: (left: 3pt + DARK),
  inset: (x: 12pt, y: 10pt),
  radius: 2pt,
  [
    #set par(first-line-indent: 0pt, leading: 0.55em)
    #set text(size: 9.5pt)
    #text(weight: "bold", size: 10pt)[Reviewer access.] The deployed system is reachable directly with the credentials below.

    #v(0.3em)
    #grid(
      columns: (auto, 1fr),
      column-gutter: 0.8em,
      row-gutter: 0.35em,
      text(weight: "bold")[Endpoint:], link("https://lasalle.generateeve.com"),
      text(weight: "bold")[Source:], link("https://github.com/joe-carr-data/lasalle-wiki-tutor"),
      text(weight: "bold")[Access token:],
      if access-token != none [
        #raw(access-token)
      ] else [
        #emph[distributed out of band on request to the corresponding author]
      ],
    )

    #v(0.3em)
    #text(size: 8.5pt, fill: rgb("#4B5563"))[Paste the token into the gate UI on first load, or send it as the `X-Access-Token` header on any `/api/wiki-tutor/*` request. The token is rotated independently of this release; if it has been rotated, contact the corresponding author for the current value.]
  ],
)

#v(0.6em)

The system runs publicly at #link("https://lasalle.generateeve.com"). The deployment is intentionally minimal so the cost story is honest: a single AWS EC2 `t3.micro` in the `eu-west-1` region, with Caddy terminating TLS via Let's Encrypt on ports 80 and 443, `uvicorn` serving FastAPI under `systemd` on the loopback interface, and `mongo:6.0` running in `docker compose` on the same host. The fixed monthly cost is approximately fourteen US dollars (`t3.micro` at \$7.50, a 30 GB `gp3` root volume at \$2.40, a public IPv4 at \$3.60 since the 2024 pricing change, daily EBS snapshots under \$0.50, no Elastic IP charge while attached to a running instance, no managed database charge). @fig:deployment shows the topology.

#figure(deployment, kind: image,
  caption: [Deployment topology. Single `t3.micro` instance with Caddy, uvicorn, and Mongo in docker compose. SSM Session Manager replaces SSH. Terraform provisions the entire stack.],
) <fig:deployment>

== Access mechanism

Public access is gated by a single shared-secret token validated server-side. The client presents the token in an `X-Access-Token` header; every `/api/wiki-tutor/*` endpoint applies the `require_access_token` FastAPI dependency, which performs a constant-time string comparison against the `WIKI_TUTOR_ACCESS_TOKEN` environment variable. A separate `/api/auth/validate` endpoint exists for the gate UI to test the token before storing it in the browser; this endpoint is protected by a per-IP rate limiter (ten attempts per minute, with a `Retry-After` header on the response) so brute-force attempts are bounded. The token in use at the time of writing is reproduced in the reviewer-access box at the head of this section; it is rotated independently of the source release, and the corresponding author distributes the current value out of band on request after rotation.

== Operational discipline

Operations on the instance happen exclusively through AWS Systems Manager Session Manager. There is no port 22 in the security group and no SSH key pair is provisioned. The instance's IAM role carries the `AmazonSSMManagedInstanceCore` managed policy and an inline policy scoped to read the two SSM Parameter Store entries that hold the OpenAI API key and the access token. IMDSv2 is required (`http_tokens = required`, `http_put_response_hop_limit = 1`) so container workloads cannot reach the instance metadata service even if the docker daemon were compromised. The root EBS volume is encrypted at rest. A Data Lifecycle Manager policy snapshots the root volume daily at 03:00 UTC and retains seven snapshots; the snapshots persist after `terraform destroy` and must be manually deleted to stop incurring storage charges.

Updates take two forms. To ship new code we run `aws ssm send-command` with a small inline script that `git fetch && git reset --hard origin/main`, restarts the `wiki-tutor` systemd service, and confirms `/health` returns 200. To rotate the wiki corpus we ship a new GitHub Release tagged `wiki-latest` whose asset is a tarball of the wiki tree, then run the same SSM command pattern to call `scripts/fetch_wiki.sh --force` and restart. The corpus and the application have separate release cadences, which lets the corpus be re-extracted and re-paired without a code change and vice versa.

== Code and data availability

The implementation is open source under the MIT license at #link("https://github.com/joe-carr-data/lasalle-wiki-tutor"). The repository contains the crawler, the wiki builder, the catalog API, the agent and tool definitions, the FastAPI server, the React client, the Terraform infrastructure module, and the evaluation scripts that produced every figure and table in this paper. The rendered wiki corpus (approximately 50 MB compressed) is published as a GitHub Release asset under the rolling `wiki-latest` tag and is fetched idempotently by `scripts/fetch_wiki.sh`. The raw HTML scrape inputs (`data/`) are not redistributed; reproducing them from scratch requires re-running the polite crawl against `salleurl.edu` over approximately eight to ten hours. The `paper/` directory of the repository contains the Typst source of this manuscript, the scripts in `paper/scripts/` that produce every data file in `paper/data/`, and the figure-generation code under `paper/scripts/make_figures.py` and `paper/scripts/make_schematics.py`. The diagrams in this paper that render as inline Typst figures are defined in `paper/diagrams.typ`.
