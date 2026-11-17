//! Local study server. Binds to loopback and serves `web/` plus the solver API.
//!
//! ```text
//! cargo run --release --bin gto-server -- --port 8080
//! ```

use gto_solver::api::{error_json, solve_request};
use gto_solver::preflop::{load_library, PreflopLibrary};
use std::collections::HashMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Instant;
use tiny_http::{Header, Method, Request, Response, Server, StatusCode};

fn main() {
    let mut port = 8080u16;
    let args: Vec<String> = env::args().skip(1).collect();
    let mut i = 0;
    while i < args.len() {
        if args[i] == "--port" {
            i += 1;
            port = args.get(i).and_then(|s| s.parse().ok()).unwrap_or(8080);
        }
        i += 1;
    }
    let library_path = find_library();
    let web_dir = find_web();
    let lib = load_library(&library_path.to_string_lossy()).unwrap_or_else(|e| {
        eprintln!("{e}");
        std::process::exit(1);
    });
    let index = index_library(&lib);
    let addr = format!("127.0.0.1:{port}");
    let server = Server::http(&addr).unwrap_or_else(|e| {
        eprintln!("could not bind {addr}: {e}");
        std::process::exit(1);
    });
    eprintln!("8-max study tool at http://{addr}");
    eprintln!(
        "preflop library {} ({} nodes, {} iterations)",
        library_path.display(),
        lib.nodes.len(),
        lib.iterations
    );
    for request in server.incoming_requests() {
        if let Err(e) = handle(request, &lib, &index, &web_dir) {
            eprintln!("request failed: {e}");
        }
    }
}

struct NodeRef {
    index: usize,
}

fn index_library(lib: &PreflopLibrary) -> HashMap<(String, String), NodeRef> {
    lib.nodes
        .iter()
        .enumerate()
        .map(|(index, n)| ((n.player.clone(), n.history.clone()), NodeRef { index }))
        .collect()
}

fn handle(
    mut request: Request,
    lib: &PreflopLibrary,
    index: &HashMap<(String, String), NodeRef>,
    web_dir: &Path,
) -> Result<(), String> {
    let url = request.url().to_string();
    let path = url.split('?').next().unwrap_or("/");
    let method = request.method().clone();
    if method == Method::Post && path == "/api/solve" {
        let mut body = String::new();
        request
            .as_reader()
            .read_to_string(&mut body)
            .map_err(|e| e.to_string())?;
        let started = Instant::now();
        let (status, text) = match solve_request(&body) {
            Ok(text) => (StatusCode(200), text),
            Err(err) => (StatusCode(400), error_json(&err)),
        };
        eprintln!(
            "POST /api/solve -> {} in {:.2}s",
            status.0,
            started.elapsed().as_secs_f64()
        );
        respond(request, status, "application/json", text.into_bytes())?;
        return Ok(());
    }
    if method == Method::Get && path == "/api/preflop/meta" {
        let nodes: Vec<_> = lib
            .nodes
            .iter()
            .map(|n| {
                serde_json::json!({
                    "player": n.player,
                    "history": n.history,
                    "actions": n.actions,
                })
            })
            .collect();
        let text = serde_json::json!({
            "iterations": lib.iterations,
            "algorithm": lib.algorithm,
            "alpha": lib.alpha,
            "beta": lib.beta,
            "gamma": lib.gamma,
            "stack_bb": lib.stack_bb,
            "hands": lib.hands,
            "limits": lib.limits,
            "nodes": nodes,
        })
        .to_string();
        respond(
            request,
            StatusCode(200),
            "application/json",
            text.into_bytes(),
        )?;
        return Ok(());
    }
    if method == Method::Get && path == "/api/preflop/node" {
        let q = query(&url);
        let player = q.get("player").cloned().unwrap_or_default();
        let history = q.get("history").cloned().unwrap_or_default();
        let Some(node_ref) = index.get(&(player.clone(), history.clone())) else {
            respond(
                request,
                StatusCode(404),
                "application/json",
                error_json("no such node").into_bytes(),
            )?;
            return Ok(());
        };
        let node = &lib.nodes[node_ref.index];
        let n_act = node.actions.len();
        let mut rows = Vec::with_capacity(lib.hands.len());
        for h in 0..lib.hands.len() {
            let slice = &node.strategy_bp[h * n_act..(h + 1) * n_act];
            rows.push(
                slice
                    .iter()
                    .map(|&b| b as f64 / 10_000.0)
                    .collect::<Vec<_>>(),
            );
        }
        let text = serde_json::json!({
            "player": node.player,
            "history": node.history,
            "actions": node.actions,
            "hands": lib.hands,
            "strategy": rows,
        })
        .to_string();
        respond(
            request,
            StatusCode(200),
            "application/json",
            text.into_bytes(),
        )?;
        return Ok(());
    }
    if method == Method::Get {
        let rel = match path {
            "/" | "" => "index.html",
            "/app.js" => "app.js",
            "/styles.css" => "styles.css",
            _ => {
                respond(
                    request,
                    StatusCode(404),
                    "text/plain",
                    b"not found".to_vec(),
                )?;
                return Ok(());
            }
        };
        let file = web_dir.join(rel);
        match fs::read(&file) {
            Ok(bytes) => {
                let ctype = if rel.ends_with(".js") {
                    "text/javascript"
                } else if rel.ends_with(".css") {
                    "text/css"
                } else {
                    "text/html; charset=utf-8"
                };
                respond(request, StatusCode(200), ctype, bytes)?;
            }
            Err(_) => {
                respond(
                    request,
                    StatusCode(404),
                    "text/plain",
                    b"missing file".to_vec(),
                )?;
            }
        }
        return Ok(());
    }
    respond(
        request,
        StatusCode(405),
        "text/plain",
        b"method not allowed".to_vec(),
    )?;
    Ok(())
}

fn respond(
    request: Request,
    status: StatusCode,
    content_type: &str,
    body: Vec<u8>,
) -> Result<(), String> {
    let header =
        Header::from_bytes(b"Content-Type", content_type.as_bytes()).map_err(|_| "header")?;
    let len = body.len();
    request
        .respond(Response::new(
            status,
            vec![header],
            std::io::Cursor::new(body),
            Some(len),
            None,
        ))
        .map_err(|e| e.to_string())
}

fn query(url: &str) -> HashMap<String, String> {
    let mut out = HashMap::new();
    let Some(q) = url.split_once('?').map(|s| s.1) else {
        return out;
    };
    for part in q.split('&') {
        if part.is_empty() {
            continue;
        }
        let (k, v) = part.split_once('=').unwrap_or((part, ""));
        out.insert(decode(k), decode(v));
    }
    out
}

fn decode(raw: &str) -> String {
    let bytes = raw.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            if let Ok(v) =
                u8::from_str_radix(std::str::from_utf8(&bytes[i + 1..i + 3]).unwrap_or(""), 16)
            {
                out.push(v);
                i += 3;
                continue;
            }
        }
        if bytes[i] == b'+' {
            out.push(b' ');
        } else {
            out.push(bytes[i]);
        }
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn find_library() -> PathBuf {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("data/preflop_100bb_8max.json");
    let candidates = [
        manifest.clone(),
        PathBuf::from("data/preflop_100bb_8max.json"),
        PathBuf::from("solver/data/preflop_100bb_8max.json"),
    ];
    candidates
        .into_iter()
        .find(|p| p.exists())
        .unwrap_or(manifest)
}

fn find_web() -> PathBuf {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../web");
    if manifest.join("index.html").exists() {
        manifest
    } else if Path::new("web/index.html").exists() {
        PathBuf::from("web")
    } else {
        PathBuf::from("../web")
    }
}
