"use client";

import { useState, useEffect, useRef } from "react";

interface CVData {
  name: string;
  contact_info: string;
  skills: string[];
  experience: string;
}

interface JobMatch {
  job_id: number;
  title: string;
  company: string;
  description: string;
  url: string;
  skills: string;
  score: number;
}

interface StateValues {
  user_id?: string;
  cv_data?: CVData;
  matched_jobs?: JobMatch[];
  status?: string;
  human_approved?: boolean;
}

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [statusText, setStatusText] = useState<string>("Upload your CV to begin matching.");
  const [state, setState] = useState<StateValues | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isApproving, setIsApproving] = useState(false);
  
  const pollingRef = useRef<NodeJS.Timeout | null>(null);

  // Poll status endpoint
  useEffect(() => {
    if (!threadId) return;

    const pollStatus = async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/v1/status/${threadId}`);
        if (!res.ok) return;
        
        const data: StateValues = await res.json();
        setState(data);

        // Update status text based on backend state
        if (data.status === "parsing_cv") {
          setStatusText("Gemini is reading and structuring your CV...");
        } else if (data.status?.startsWith("parsing_failed")) {
          setStatusText("Failed to parse CV with Gemini. Please check API Key / rate limits.");
          stopPolling();
        } else if (data.status === "matching") {
          setStatusText("Qdrant is performing semantic search and matching jobs...");
        } else if (data.status?.startsWith("matching_failed")) {
          setStatusText("Failed to find job matches. Make sure Qdrant is seeded.");
          stopPolling();
        } else if (data.status === "review_pending") {
          setStatusText("Awaiting human review to complete application forms.");
          stopPolling();
        } else if (data.status === "submitted") {
          setStatusText("Applications submitted successfully!");
          stopPolling();
        }
      } catch (err) {
        console.error("Polling error:", err);
      }
    };

    // Run first immediately
    pollStatus();
    
    // Set interval
    pollingRef.current = setInterval(pollStatus, 2000);

    return () => stopPolling();
  }, [threadId]);

  const stopPolling = () => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  };

  const handleDragLeave = () => {
    setIsDragOver(false);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      setFile(e.dataTransfer.files[0]);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFile(e.target.files[0]);
    }
  };

  const uploadFile = async () => {
    if (!file) return;
    setIsUploading(true);
    setStatusText("Uploading CV file to API gateway...");
    setState(null);
    setThreadId(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("http://localhost:8000/api/v1/upload-cv", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) throw new Error("Upload failed");

      const data = await res.json();
      setThreadId(data.thread_id);
      setIsUploading(false);
    } catch (err) {
      console.error(err);
      setStatusText("Upload failed. Make sure the backend services are running.");
      setIsUploading(false);
    }
  };

  const approveApplication = async () => {
    if (!threadId) return;
    setIsApproving(true);
    setStatusText("Approving and resuming Playwright worker task...");

    try {
      const res = await fetch("http://localhost:8000/api/v1/resume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: threadId }),
      });

      if (!res.ok) throw new Error("Approval failed");
      
      setIsApproving(false);
      // Restart polling to wait for the "submitted" status
      setThreadId(null);
      setTimeout(() => setThreadId(threadId), 500);
    } catch (err) {
      console.error(err);
      setStatusText("Approval failed. Please try again.");
      setIsApproving(false);
    }
  };

  const getStepClass = (step: string) => {
    const status = state?.status || "";
    if (step === "parsing") {
      if (status === "parsing_cv") return "border-cyan-500 text-cyan-400 bg-cyan-950/30 animate-pulse";
      if (status.startsWith("parsing_failed")) return "border-red-500 text-red-400 bg-red-950/20";
      if (["parsing_complete", "matching", "matching_complete", "review_pending", "submitted"].includes(status)) {
        return "border-emerald-500 text-emerald-400 bg-emerald-950/30";
      }
    }
    if (step === "matching") {
      if (status === "matching") return "border-cyan-500 text-cyan-400 bg-cyan-950/30 animate-pulse";
      if (status.startsWith("matching_failed")) return "border-red-500 text-red-400 bg-red-950/20";
      if (["matching_complete", "review_pending", "submitted"].includes(status)) {
        return "border-emerald-500 text-emerald-400 bg-emerald-950/30";
      }
    }
    if (step === "review") {
      if (status === "review_pending") return "border-yellow-500 text-yellow-400 bg-yellow-950/30 animate-pulse";
      if (["submitted"].includes(status)) {
        return "border-emerald-500 text-emerald-400 bg-emerald-950/30";
      }
    }
    if (step === "submit") {
      if (status === "submitted") return "border-emerald-500 text-emerald-400 bg-emerald-950/30";
    }
    return "border-slate-800 text-slate-500 bg-slate-900/10";
  };

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans relative overflow-hidden">
      {/* Background decoration */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none z-0">
        <div className="absolute -top-[40%] -left-[20%] w-[80%] h-[80%] rounded-full bg-cyan-950/20 blur-[120px]" />
        <div className="absolute top-[20%] right-[-10%] w-[60%] h-[60%] rounded-full bg-indigo-950/25 blur-[120px]" />
      </div>

      <header className="border-b border-slate-900 bg-slate-950/80 backdrop-blur-md sticky top-0 z-50 py-4 px-6 md:px-12 flex justify-between items-center relative">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-cyan-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
            <svg className="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <div>
            <span className="font-bold text-lg bg-gradient-to-r from-white via-slate-100 to-slate-400 bg-clip-text text-transparent">Antigravity Agent</span>
            <span className="text-xs block text-slate-500 font-medium">CV Matcher & Automated Apply</span>
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg text-slate-400 font-mono">
          <span className="h-2 w-2 rounded-full bg-emerald-500 inline-block animate-ping" />
          SYSTEM ACTIVE
        </div>
      </header>

      <section className="relative z-10 flex-1 max-w-6xl w-full mx-auto p-6 md:p-12 flex flex-col gap-8">
        
        {/* Step 1: Upload */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          <div className="lg:col-span-2 bg-slate-900/40 border border-slate-900 backdrop-blur-md rounded-2xl p-6 md:p-8 shadow-2xl flex flex-col gap-6">
            <h2 className="text-xl font-semibold flex items-center gap-2.5">
              <span className="h-6 w-6 rounded bg-cyan-950 border border-cyan-800 text-cyan-400 text-xs flex items-center justify-center font-bold">1</span>
              CV / Resume Ingestion
            </h2>

            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              className={`border-2 border-dashed rounded-xl p-8 text-center transition-all cursor-pointer ${
                isDragOver ? "border-cyan-500 bg-cyan-950/10 shadow-lg shadow-cyan-500/5" : "border-slate-800 hover:border-slate-700 bg-slate-950/20"
              }`}
            >
              <input
                type="file"
                id="cv-file"
                onChange={handleFileChange}
                accept=".pdf,.jpg,.jpeg,.png"
                className="hidden"
              />
              <label htmlFor="cv-file" className="cursor-pointer flex flex-col items-center gap-3">
                <div className="h-12 w-12 rounded-lg bg-slate-900 border border-slate-800 flex items-center justify-center text-slate-400">
                  <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                  </svg>
                </div>
                <div>
                  <p className="font-medium text-slate-300">Drag & drop your CV file here</p>
                  <p className="text-xs text-slate-500 mt-1">Supports PDF, JPG, PNG up to 10MB</p>
                </div>
                <div className="bg-slate-900 hover:bg-slate-850 border border-slate-800 text-xs font-semibold px-4 py-2 rounded-lg text-slate-300 mt-2 transition">
                  Browse Files
                </div>
              </label>
            </div>

            {file && (
              <div className="flex items-center justify-between bg-slate-950/60 border border-slate-900 p-4 rounded-xl">
                <div className="flex items-center gap-3">
                  <div className="h-10 w-10 bg-slate-900 border border-slate-800 rounded-lg flex items-center justify-center text-cyan-400">
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                  </div>
                  <div className="text-left">
                    <p className="text-sm font-semibold text-slate-300 truncate max-w-[200px] md:max-w-[300px]">{file.name}</p>
                    <p className="text-xs text-slate-500">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                  </div>
                </div>
                <button
                  onClick={uploadFile}
                  disabled={isUploading}
                  className="bg-gradient-to-r from-cyan-500 to-indigo-600 hover:from-cyan-400 hover:to-indigo-500 text-white font-semibold text-sm px-6 py-2.5 rounded-lg shadow-lg shadow-cyan-500/10 transition disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isUploading ? "Uploading..." : "Start Matching"}
                </button>
              </div>
            )}
          </div>

          {/* Workflow Stage Map */}
          <div className="bg-slate-900/40 border border-slate-900 backdrop-blur-md rounded-2xl p-6 md:p-8 shadow-2xl flex flex-col gap-6">
            <h2 className="text-xl font-semibold flex items-center gap-2.5">
              <span className="h-6 w-6 rounded bg-indigo-950 border border-indigo-800 text-indigo-400 text-xs flex items-center justify-center font-bold">2</span>
              Agent Console
            </h2>

            <div className="flex-1 flex flex-col gap-4 justify-between">
              <div className="flex flex-col gap-3">
                <div className={`border rounded-xl p-3 text-xs font-semibold flex items-center gap-3 transition-all ${getStepClass("parsing")}`}>
                  <span className="h-5 w-5 rounded-full border border-current flex items-center justify-center text-[10px]">1</span>
                  Gemini Parsing
                </div>
                <div className={`border rounded-xl p-3 text-xs font-semibold flex items-center gap-3 transition-all ${getStepClass("matching")}`}>
                  <span className="h-5 w-5 rounded-full border border-current flex items-center justify-center text-[10px]">2</span>
                  Qdrant Vector Matching
                </div>
                <div className={`border rounded-xl p-3 text-xs font-semibold flex items-center gap-3 transition-all ${getStepClass("review")}`}>
                  <span className="h-5 w-5 rounded-full border border-current flex items-center justify-center text-[10px]">3</span>
                  Human Checkpoint
                </div>
                <div className={`border rounded-xl p-3 text-xs font-semibold flex items-center gap-3 transition-all ${getStepClass("submit")}`}>
                  <span className="h-5 w-5 rounded-full border border-current flex items-center justify-center text-[10px]">4</span>
                  Submit Application
                </div>
              </div>

              <div className="p-4 bg-slate-950/80 border border-slate-900 rounded-xl text-[11px] text-slate-400 font-mono flex items-start gap-2.5 leading-relaxed">
                <svg className="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span>Console: {statusText}</span>
              </div>
            </div>
          </div>
        </div>

        {/* Step 3: Extracted CV Details and Match Results */}
        {state && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
            {/* Extracted Profile */}
            <div className="lg:col-span-1 bg-slate-900/40 border border-slate-900 backdrop-blur-md rounded-2xl p-6 shadow-2xl flex flex-col gap-5">
              <h3 className="font-semibold text-lg border-b border-slate-800 pb-3 flex items-center justify-between text-slate-200">
                Extracted Profile
                <span className="text-[10px] bg-emerald-950 text-emerald-400 border border-emerald-800 px-2 py-0.5 rounded">Gemini Validated</span>
              </h3>
              
              {state.cv_data ? (
                <div className="flex flex-col gap-4 text-sm">
                  <div>
                    <span className="text-xs text-slate-500 font-semibold uppercase block tracking-wider">Candidate Name</span>
                    <span className="font-semibold text-slate-200">{state.cv_data.name || "N/A"}</span>
                  </div>
                  <div>
                    <span className="text-xs text-slate-500 font-semibold uppercase block tracking-wider">Contact Info</span>
                    <span className="text-slate-300 font-mono text-xs">{state.cv_data.contact_info || "N/A"}</span>
                  </div>
                  <div>
                    <span className="text-xs text-slate-500 font-semibold uppercase block tracking-wider mb-1.5">Skills</span>
                    <div className="flex flex-wrap gap-1.5">
                      {state.cv_data.skills && state.cv_data.skills.length > 0 ? (
                        state.cv_data.skills.map((skill, index) => (
                          <span key={index} className="text-[10px] bg-slate-900 border border-slate-800 text-cyan-400 px-2 py-1 rounded-md font-medium">
                            {skill}
                          </span>
                        ))
                      ) : (
                        <span className="text-slate-500 italic text-xs">No skills listed</span>
                      )}
                    </div>
                  </div>
                  <div>
                    <span className="text-xs text-slate-500 font-semibold uppercase block tracking-wider">Experience Summary</span>
                    <p className="text-xs text-slate-400 leading-relaxed mt-1 font-sans max-h-[320px] overflow-y-auto pr-1.5 whitespace-pre-line scrollbar-thin">
                      {state.cv_data.experience || "N/A"}
                    </p>
                  </div>
                </div>
              ) : (
                <div className="text-slate-500 italic text-center text-sm py-12">Parsing resume data...</div>
              )}
            </div>

            {/* Match Results */}
            <div className="lg:col-span-2 flex flex-col gap-6">
              
              {/* Review Checkpoint (HITL) */}
              {state.status === "review_pending" && (
                <div className="bg-gradient-to-tr from-yellow-950/20 via-slate-900/60 to-indigo-950/20 border border-yellow-500/20 backdrop-blur-md rounded-2xl p-6 shadow-2xl flex flex-col md:flex-row md:items-center justify-between gap-6">
                  <div className="flex gap-4">
                    <div className="h-12 w-12 rounded-xl bg-yellow-500/10 border border-yellow-500/20 flex items-center justify-center text-yellow-400 shrink-0">
                      <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                      </svg>
                    </div>
                    <div>
                      <h4 className="font-bold text-slate-200">Human-In-The-Loop Checkpoint</h4>
                      <p className="text-xs text-slate-400 leading-relaxed mt-0.5">
                        Please review the job matches below. Clicking approve will launch the Playwright browser worker to submit your application.
                      </p>
                    </div>
                  </div>
                  <button
                    onClick={approveApplication}
                    disabled={isApproving}
                    className="bg-yellow-500 hover:bg-yellow-400 text-slate-950 font-bold text-sm px-6 py-3 rounded-xl transition shadow-lg shadow-yellow-500/10 shrink-0"
                  >
                    {isApproving ? "Submitting..." : "Approve & Apply"}
                  </button>
                </div>
              )}

              {/* Submitted Celebration */}
              {state.status === "submitted" && (
                <div className="bg-gradient-to-tr from-emerald-950/20 via-slate-900/60 to-cyan-950/20 border border-emerald-500/30 backdrop-blur-md rounded-2xl p-6 shadow-2xl flex items-center gap-4">
                  <div className="h-12 w-12 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shrink-0">
                    <svg className="w-6 h-6 animate-bounce" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  </div>
                  <div>
                    <h4 className="font-bold text-slate-200">Application Submitted!</h4>
                    <p className="text-xs text-slate-400 leading-relaxed mt-0.5">
                      The autonomous worker completed the form submission securely using Playwright.
                    </p>
                  </div>
                </div>
              )}

              <div className="bg-slate-900/40 border border-slate-900 backdrop-blur-md rounded-2xl p-6 shadow-2xl flex flex-col gap-5">
                <h3 className="font-semibold text-lg border-b border-slate-800 pb-3 flex items-center justify-between text-slate-200">
                  Semantic Job Matches
                  <span className="text-[10px] bg-cyan-950 text-cyan-400 border border-cyan-800 px-2 py-0.5 rounded">Qdrant Indexed</span>
                </h3>

                <div className="flex flex-col gap-4">
                  {state.matched_jobs && state.matched_jobs.length > 0 ? (
                    state.matched_jobs.map((job) => (
                      <div key={job.job_id} className="border border-slate-800 bg-slate-950/40 hover:bg-slate-950/80 hover:border-slate-700 p-4 rounded-xl flex flex-col md:flex-row justify-between items-start md:items-center gap-4 transition-all">
                        <div className="flex-1 text-left">
                          <span className="text-[10px] text-cyan-400 font-semibold bg-slate-900 border border-slate-800 px-2 py-0.5 rounded-md uppercase">
                            {job.company}
                          </span>
                          <h4 className="font-bold text-slate-200 text-sm mt-1">{job.title}</h4>
                          <p className="text-xs text-slate-400 line-clamp-2 mt-1 leading-relaxed">{job.description}</p>
                        </div>
                        <div className="flex flex-row md:flex-col items-center md:items-end justify-between w-full md:w-auto gap-4 shrink-0 border-t border-slate-900 md:border-0 pt-3 md:pt-0">
                          <div>
                            <span className="text-[10px] text-slate-500 block uppercase font-bold tracking-wider">Semantic Match</span>
                            <span className="font-mono font-bold text-emerald-400 text-sm">{Math.round(job.score * 100)}% Match</span>
                          </div>
                          <a
                            href={job.url}
                            target="_blank"
                            rel="noreferrer"
                            className="bg-slate-950 border border-slate-850 hover:border-slate-700 text-xs font-semibold px-3.5 py-2 rounded-lg text-slate-300 transition"
                          >
                            Job Details
                          </a>
                        </div>
                      </div>
                    ))
                  ) : (
                    <div className="text-slate-500 italic text-center py-12 text-sm">No job matches found. Seed Qdrant first.</div>
                  )}
                </div>
              </div>

            </div>
          </div>
        )}
      </section>
    </main>
  );
}