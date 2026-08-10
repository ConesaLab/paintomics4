/* global Ext, APP_VERSION, dragula */

//# sourceURL=PA_Step1Views.js
/*
* (C) Copyright 2014 The Genomics of Gene Expression Lab, CIPF
* (http://bioinfo.cipf.es/aconesawp) and others.
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of the GNU Lesser General Public License
* (LGPL) version 3 which accompanies this distribution, and is available at
* http://www.gnu.org/licenses/lgpl.html
*
* This library is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
* Lesser General Public License for more details.
*
* Contributors:
*     Rafael Hernandez de Diego
*     rhernandez@cipf.es
*     Ana Conesa Cegarra
*     aconesa@cipf.es
* THIS FILE CONTAINS THE FOLLOWING COMPONENT DECLARATION
* - PA_Step1JobView
* - OmicSubmittingPanel
* - RegionBasedOmicSubmittingPanel
*/
/* The landing hero's explainer diagram: your omic data -> mapped onto
   pathways -> ranked and painted, with the AI strip beneath.

   This replaces the graphical abstract in the hero slot. That asset is a
   1622x996 raster of a scientific figure with embedded screenshots and
   labels, and the hero renders it at 340px -- a 4.8x downscale at which
   none of its text can be read. It is still the right asset for print and
   for the docs, so the link below the diagram opens it full size.

   Ported from the design system's marketing/PaintomicsFlow, with two
   deliberate departures. The ramp is the product's own rather than the
   system's ColorBrewer values: the component's stated constraint is that
   these colours match the painted pathway diagrams, and what the product
   actually paints is getColor(..., 'bwr') in PA_Step3Views.js -- a pure RGB
   ramp, red at max, white at zero, blue at min. And the three beats are
   stacked as rows rather than set as columns, so the viewBox is 1:1 with
   the rendered width and every label is drawn at the size it is read at;
   the system's 660-wide landscape version has to shrink to 0.65 in this
   slot, which takes its 11px labels down to about 7px. */
var PO_HERO_FLOW_SVG =
	'<svg class="po-hero-flow" viewBox="0 0 460 408" role="img" style="display:block;width:100%;height:auto;font-family:var(--pa-font-sans)" aria-label="How PaintOmics works: your omic data is mapped onto pathways, then ranked and painted" xmlns="http://www.w3.org/2000/svg">' +
	'<title>How PaintOmics works</title>' +
	'<rect x=".5" y="0.5" width="459" height="111" rx="8" fill="#FFFFFF" stroke="#E4E4E7"/>' +
	'<circle cx="30" cy="30" r="11" fill="#AD5022"/>' +
	'<text x="30" y="34.5" text-anchor="middle" font-size="12" font-weight="700" fill="#FFFFFF">1</text>' +
	'<text x="50" y="30" font-size="14" font-weight="600" fill="#27272A">Your omic data</text>' +
	'<text x="50" y="49" font-size="11.5" fill="#71717A">One file per omic type</text>' +
	'<rect x="258" y="12" width="186" height="20" rx="5" fill="#55C9A6" fill-opacity=".16" stroke="#55C9A6" stroke-opacity=".55"/>' +
	'<circle cx="271" cy="22" r="4.5" fill="#55C9A6"/>' +
	'<text x="283" y="26" font-size="11" fill="#3F3F46">Gene expression</text>' +
	'<rect x="410" y="18" width="7" height="7" rx="1" fill="#FF0000" stroke="#878787" stroke-width="1"/>' +
	'<rect x="419" y="18" width="7" height="7" rx="1" fill="#FF8080" stroke="#878787" stroke-width="1"/>' +
	'<rect x="428" y="18" width="7" height="7" rx="1" fill="#8080FF" stroke="#878787" stroke-width="1"/>' +
	'<rect x="258" y="34" width="186" height="20" rx="5" fill="#79B0EC" fill-opacity=".16" stroke="#79B0EC" stroke-opacity=".55"/>' +
	'<circle cx="271" cy="44" r="4.5" fill="#79B0EC"/>' +
	'<text x="283" y="48" font-size="11" fill="#3F3F46">Metabolomics</text>' +
	'<rect x="410" y="40" width="7" height="7" rx="1" fill="#8080FF" stroke="#878787" stroke-width="1"/>' +
	'<rect x="419" y="40" width="7" height="7" rx="1" fill="#FFFFFF" stroke="#878787" stroke-width="1"/>' +
	'<rect x="428" y="40" width="7" height="7" rx="1" fill="#FF0000" stroke="#878787" stroke-width="1"/>' +
	'<rect x="258" y="56" width="186" height="20" rx="5" fill="#B4A1DD" fill-opacity=".16" stroke="#B4A1DD" stroke-opacity=".55"/>' +
	'<circle cx="271" cy="66" r="4.5" fill="#B4A1DD"/>' +
	'<text x="283" y="70" font-size="11" fill="#3F3F46">Proteomics</text>' +
	'<rect x="410" y="62" width="7" height="7" rx="1" fill="#FF8080" stroke="#878787" stroke-width="1"/>' +
	'<rect x="419" y="62" width="7" height="7" rx="1" fill="#FF0000" stroke="#878787" stroke-width="1"/>' +
	'<rect x="428" y="62" width="7" height="7" rx="1" fill="#FFFFFF" stroke="#878787" stroke-width="1"/>' +
	'<rect x="258" y="78" width="186" height="20" rx="5" fill="#738B9D" fill-opacity=".16" stroke="#738B9D" stroke-opacity=".55"/>' +
	'<circle cx="271" cy="88" r="4.5" fill="#738B9D"/>' +
	'<text x="283" y="92" font-size="11" fill="#3F3F46">+ 3 more omic types</text>' +
	'<rect x=".5" y="122.5" width="459" height="111" rx="8" fill="#FFFFFF" stroke="#E4E4E7"/>' +
	'<circle cx="30" cy="152" r="11" fill="#AD5022"/>' +
	'<text x="30" y="156.5" text-anchor="middle" font-size="12" font-weight="700" fill="#FFFFFF">2</text>' +
	'<text x="50" y="152" font-size="14" font-weight="600" fill="#27272A">Mapped to pathways</text>' +
	'<text x="50" y="171" font-size="11.5" fill="#71717A">KEGG · Reactome · MapMan</text>' +
	'<g transform="translate(307.6,145.8) scale(0.62)">' +
	'<line x1="12" y1="30" x2="52" y2="12" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="52" y1="12" x2="98" y2="34" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="12" y1="30" x2="54" y2="56" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="54" y1="56" x2="98" y2="34" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="98" y1="34" x2="128" y2="74" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="54" y1="56" x2="74" y2="92" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="74" y1="92" x2="18" y2="78" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="74" y1="92" x2="128" y2="74" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="18" y1="78" x2="12" y2="30" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<circle cx="12" cy="30" r="9" fill="#F3F3F3" stroke="#878787" stroke-width="2.4"/>' +
	'<circle cx="52" cy="12" r="9" fill="#F3F3F3" stroke="#878787" stroke-width="2.4"/>' +
	'<rect x="39" y="50" width="10" height="12" fill="#F3F3F3" stroke="#878787" stroke-width="1.6"/>' +
	'<rect x="49" y="50" width="10" height="12" fill="#F3F3F3" stroke="#878787" stroke-width="1.6"/>' +
	'<rect x="59" y="50" width="10" height="12" fill="#F3F3F3" stroke="#878787" stroke-width="1.6"/>' +
	'<rect x="83" y="28" width="10" height="12" fill="#F3F3F3" stroke="#878787" stroke-width="1.6"/>' +
	'<rect x="93" y="28" width="10" height="12" fill="#F3F3F3" stroke="#878787" stroke-width="1.6"/>' +
	'<rect x="103" y="28" width="10" height="12" fill="#F3F3F3" stroke="#878787" stroke-width="1.6"/>' +
	'<circle cx="128" cy="74" r="9" fill="#F3F3F3" stroke="#878787" stroke-width="2.4"/>' +
	'<circle cx="74" cy="92" r="9" fill="#F3F3F3" stroke="#878787" stroke-width="2.4"/>' +
	'<circle cx="18" cy="78" r="9" fill="#F3F3F3" stroke="#878787" stroke-width="2.4"/>' +
	'</g>' +
	'<rect x=".5" y="244.5" width="459" height="111" rx="8" fill="#FFFFFF" stroke="#E4E4E7"/>' +
	'<circle cx="30" cy="274" r="11" fill="#AD5022"/>' +
	'<text x="30" y="278.5" text-anchor="middle" font-size="12" font-weight="700" fill="#FFFFFF">3</text>' +
	'<text x="50" y="274" font-size="14" font-weight="600" fill="#27272A">Ranked and painted</text>' +
	'<text x="50" y="293" font-size="11.5" fill="#71717A">104 of 888 pathways significant</text>' +
	'<rect x="258" y="256" width="186" height="5" rx="2.5" fill="#AD5022" opacity="1.0"/>' +
	'<rect x="258" y="265" width="138" height="5" rx="2.5" fill="#AD5022" opacity="0.7"/>' +
	'<rect x="258" y="274" width="96" height="5" rx="2.5" fill="#AD5022" opacity="0.4"/>' +
	'<g transform="translate(307.6,283.8) scale(0.62)">' +
	'<line x1="12" y1="30" x2="52" y2="12" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="52" y1="12" x2="98" y2="34" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="12" y1="30" x2="54" y2="56" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="54" y1="56" x2="98" y2="34" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="98" y1="34" x2="128" y2="74" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="54" y1="56" x2="74" y2="92" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="74" y1="92" x2="18" y2="78" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="74" y1="92" x2="128" y2="74" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<line x1="18" y1="78" x2="12" y2="30" stroke="#878787" stroke-width="1.6" stroke-opacity=".55"/>' +
	'<circle cx="12" cy="30" r="9" fill="#FF0000" stroke="#878787" stroke-width="1.6"/>' +
	'<circle cx="52" cy="12" r="9" fill="#FF8080" stroke="#878787" stroke-width="1.6"/>' +
	'<rect x="39" y="50" width="10" height="12" fill="#0000FF" stroke="#878787" stroke-width="1.6"/>' +
	'<rect x="49" y="50" width="10" height="12" fill="#8080FF" stroke="#878787" stroke-width="1.6"/>' +
	'<rect x="59" y="50" width="10" height="12" fill="#FFFFFF" stroke="#878787" stroke-width="1.6"/>' +
	'<rect x="83" y="28" width="10" height="12" fill="#FF0000" stroke="#878787" stroke-width="1.6"/>' +
	'<rect x="93" y="28" width="10" height="12" fill="#FF8080" stroke="#878787" stroke-width="1.6"/>' +
	'<rect x="103" y="28" width="10" height="12" fill="#FF0000" stroke="#878787" stroke-width="1.6"/>' +
	'<circle cx="128" cy="74" r="9" fill="#8080FF" stroke="#878787" stroke-width="1.6"/>' +
	'<circle cx="74" cy="92" r="9" fill="#FFFFFF" stroke="#878787" stroke-width="1.6"/>' +
	'<circle cx="18" cy="78" r="9" fill="#0000FF" stroke="#878787" stroke-width="1.6"/>' +
	'</g>' +
	'<rect x=".5" y="366.5" width="459" height="41" rx="8" fill="#F0F7FF" stroke="#C8D6E5"/>' +
	'<g transform="translate(18,374) scale(1)" color="#4A90D9">' +
	'<path d="M13 4.9 L20 9 L20 17.1 L13 21.2 L6 17.1 L6 9 Z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" opacity=".45"/>' +
	'<path d="M13 8.2 C13.4 10.5 15.5 12.6 17.8 13 C15.5 13.4 13.4 15.5 13 17.8 C12.6 15.5 10.5 13.4 8.2 13 C10.5 12.6 12.6 10.5 13 8.2 Z" fill="currentColor"/>' +
	'</g>' +
	'<text x="48" y="385" font-size="12" fill="#52525B"><tspan font-weight="600" fill="#27272A">PaintOmics AI</tspan><tspan> turns the ranked result into a written</tspan></text>' +
	'<text x="48" y="400" font-size="12" fill="#52525B">interpretation, grounded in the literature.</text>' +
	'</svg>';

/**
* The description shipped with the real STATegra example. Only used as the
* fallback when the server's catalogue is unreachable; otherwise the text is
* generated from the chosen dataset's own manifest entry.
*/
var STATEGRA_EXPERIMENT_DESIGN = "STATegra multi-omics time-course experiment in mouse B3 cell line (Mus musculus, mmu). Ikaros transcription factor expression was induced via tamoxifen treatment to trigger B-cell differentiation. Ikaros-induced vs Control samples were compared across 6 time points (0h, 2h, 6h, 12h, 18h, 24h). Values are log2 fold-changes (Ikaros/Control). Six omics layers: gene expression, proteomics, metabolomics, DNase-seq chromatin accessibility, miRNA-seq, and transcription factor activity. Goal: identify pathways and molecular mechanisms driving Ikaros-mediated B-cell differentiation across multiple regulatory levels.";

/**
* Manifest omic name -> the panel type addNewOmicSubmittingPanel builds.
*
* The manifest uses the omic names the *server* knows ("Gene expression",
* "DNase-seq"); the form uses its own panel keys ("geneexpression",
* "dnaseseq"). Matching is case-insensitive and punctuation-insensitive so a
* dataset written as "miRNA-seq", "miRNA-Seq" or "mirna seq" all land on the
* same panel -- the manifest is edited by hand and this is not worth failing on.
*
* An unrecognised name falls back to the generic "otheromic" panel rather than
* being skipped: showing a user a panel labelled with their omic's name is a
* better failure than silently loading fewer omics than the dataset contains.
*/
/**
* Put a read-only "this came from the example dataset" label in a file field.
*
* `myFilesSelectorButton.setValue(value)` defaults its origin to "mydata" and
* renders the value as `[MyData]/<value>`, which is right for a file the user
* picked out of their own storage and wrong for an example: the old panels
* displayed strings like `[MyData]/example/dnase_unmapped_values.tab`, naming a
* location that does not exist in anyone's data folder. Passing an explicit
* origin suppresses the prefix.
*
* The origin token also lands in the hidden `<prefix>_origin` field. "example"
* matches none of the branches JobInformationManager.saveFiles dispatches on
* ("client", "mydata", "inbuilt_gtf", "*filelocation*"), which is safe because
* example submissions never reach saveFiles -- the servlets resolve their files
* from the manifest and ignore the form entirely.
*
* setDisabled here disables the Browse button, which is the widget's whole
* interactive surface; the text stays selectable so it can be read and copied.
*/
function setExampleLabel(field, text) {
	if (!field) { return; }
	field.setValue("[example dataset] " + text, "example");
	field.setDisabled(true);
}

/**
* Pipeline -> the single panel type that pipeline's example needs.
*
* These three are pre-processing steps: they convert their input into
* gene-based values and hand the result to the normal pathway analysis, so an
* example for them is one panel, not one per omic.
*/
var EXAMPLE_PANEL_FOR_PIPELINE = {
	"regions2genes": "bedbasedomic",
	"mirna2genes": "mirnabasedomic",
	"more": "moreanalysis"
};

function examplePanelTypeFor(omicName) {
	var key = String(omicName || "").toLowerCase().replace(/[^a-z]/g, "");
	var byKey = {
		"geneexpression": "geneexpression",
		"proteomics": "proteomics",
		"metabolomics": "metabolomics",
		"mirnaseq": "mirnaseq",
		"mirna": "mirnaseq",
		"mirnaunmapped": "mirnaseq",
		"dnaseseq": "dnaseseq",
		"dnase": "dnaseseq",
		"dnaseunmapped": "dnaseseq",
		"transcriptionfactor": "transcriptionfactor"
	};
	return byKey[key] || "otheromic";
}

/**
* A plain-language description of a dataset, for the AI-interpretation prompt.
*
* Generated from the manifest entry rather than stored, so it cannot drift from
* the data the way a hand-written blurb does -- the previous version quoted
* feature counts ("6337 genes, 5224 DE") that no longer matched the files.
*/
function exampleExperimentDesignFor(scenario) {
	var conditions = scenario.conditions || [];
	var parts = [scenario.title + "."];

	if (scenario.summary) { parts.push(scenario.summary); }
	parts.push("Organism: " + (scenario.organism || "mmu") + ".");
	if ((scenario.omicNames || []).length) {
		parts.push("Omics layers: " + scenario.omicNames.join(", ") + ".");
	}
	if (conditions.length) {
		parts.push("Conditions (" + conditions.length + "): " +
			conditions.join(", ") + ".");
	}
	parts.push(scenario.simulated
		? "Values are simulated log2 fold-changes with a coherent signal planted " +
		  "into a chosen set of KEGG pathways; all other features are centred on zero."
		: "Values are log2 fold-changes against the control condition.");
	return parts.join(" ");
}

/*********************************************************************
* INSTALLED PATHWAY DATABASES
*
* Which of KEGG / MapMan / Reactome a job can actually use is a property of
* the server and the chosen organism, not of the form. GET /organism_databases
* reports it, read from each organism's own MongoDB, and step 1 draws its
* checkboxes from the answer: every database it names is ticked, and every
* database it does not is disabled.
*
* Fetched once per page. The map is a few hundred bytes for a hundred
* organisms and changes only when an administrator installs a species, so
* re-reading it on every change of the organism combo would buy nothing and
* put a round trip in front of a click.
***********************************************************************/
var ORGANISM_DATABASES = null;
var ORGANISM_DATABASES_REQUEST = null;
/* Whether the endpoint actually answered, which is NOT the same question as
   whether the map has an entry for an organism. species.json is written once by
   DBManager and lists what was installed when it last ran -- this repository's
   own copy offers about a hundred species on a machine that has two -- so an
   organism can be selectable in the combo and have no pathways at all. That has
   to disable every optional database, whereas an endpoint that never answered
   has to enable them. Same missing entry, opposite correct answers. */
var ORGANISM_DATABASES_READ = false;

/**
* Resolves to {organism: [databases]}, fetching it at most once.
*
* Never rejects. A server too old to have the endpoint, or one that cannot
* reach MongoDB, resolves without setting ORGANISM_DATABASES_READ, and
* getInstalledDatabasesFor() then offers everything -- which is what this form
* did before the endpoint existed. Degrading to a form that offers too much is
* recoverable; the server drops what it cannot run, exactly as it always has.
* Degrading to a form that offers nothing would make step 1 unusable.
*/
function loadOrganismDatabases() {
	if (ORGANISM_DATABASES_REQUEST === null) {
		// A Deferred that is only ever resolved, rather than the jqXHR's own
		// promise. Returning a value from a .then() failure filter recovers the
		// chain in jQuery 3 and does NOT in jQuery 1 or 2, and this file is
		// loaded next to a jquery-migrate shim -- a promise that silently stops
		// resolving would leave every optional database disabled for good.
		var ready = $.Deferred();
		ORGANISM_DATABASES_REQUEST = ready.promise();

		$.getJSON(SERVER_URL_GET_ORGANISM_DATABASES)
			.done(function(response) {
				ORGANISM_DATABASES = (response && response.databases) || {};
				ORGANISM_DATABASES_READ = true;
			})
			.fail(function() {
				console.warn("Could not read the installed pathway databases; " +
					"every database will be offered and the server will drop " +
					"the ones it cannot run.");
				ORGANISM_DATABASES = {};
			})
			.always(function() { ready.resolve(ORGANISM_DATABASES); });
	}
	return ORGANISM_DATABASES_REQUEST;
}

/**
* The databases installed for one organism, or null for "cannot tell".
*
* null is the only answer that means "offer everything and let the server drop
* what it cannot run" -- the behaviour this form had before the endpoint
* existed. It is returned when, and only when, the map could not be read.
*
* An organism the map does not mention gets ["KEGG"]: the endpoint enumerates
* the organisms that have a MongoDB database of their own, so a name missing
* from it has no pathways installed under any database, and offering MapMan or
* Reactome for it would be the same empty promise this change exists to remove.
*/
function getInstalledDatabasesFor(organism) {
	if (!ORGANISM_DATABASES_READ) { return null; }
	if (!organism) { return ["KEGG"]; }
	var installed = ORGANISM_DATABASES[organism];
	return (installed && installed.length) ? installed : ["KEGG"];
}

function PA_Step1JobView() {
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	this.name = "PA_Step1JobView";
	this.nFiles = 0;
	this.exampleMode = false;
	// Regulatory Omic analysis method, locked once chosen for the whole job.
	// null until the user picks; "pairwise" or "more" thereafter.
	this.regulatoryMethod = null;

	/*********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/
	this.isExampleMode = function() {
		return this.exampleMode;
	};
	/**
	* The example dataset the user picked, or null for the server's default.
	* Appended to the "/example" URL as an extra path segment; the routes use
	* Flask's <path:> converter, so no new endpoint is involved.
	*/
	this.getExampleScenarioId = function() {
		return this.exampleScenarioId || null;
	};
	/**
	* The pipeline the loaded example belongs to, or null when none is loaded.
	*
	* This is what tells the controller whether the *pathway* submission is
	* still an example submission. For a `pathway-acquisition` dataset it is:
	* step 1 reads the bundled files directly. For `regions2genes`,
	* `mirna2genes` and `more` it is NOT: those run first and produce real files
	* into the job's own directory, and step 1 must then be an ordinary upload
	* of that output. Sending step 1 to the example endpoint instead makes it
	* re-read the dataset's raw inputs and throw the conversion away -- observed
	* as "EXAMPLE 'regulatory-more' REGISTERED (2 omics)" in the step-1 log
	* after MORE had already produced its GENE:::REGULATOR values.
	*/
	this.getExamplePipeline = function() {
		return this.examplePipeline || null;
	};

	/*********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	/**
	* This function remove all panels and reset the application.
	*/
	this.resetViewHandler = function() {
		this.regulatoryMethod = null;
		this.controller.resetButtonClickHandler(this);
	};
	/**
	* Opens the modal that lets the user pick between Pairwise and MORE
	* the first time they add a Regulatory Omic in this job. Once chosen,
	* `this.regulatoryMethod` is locked for the rest of the session.
	*/
	this.showRegulatoryMethodChooser = function() {
		var me = this;
		var pickHandler = function(method) {
			return function() {
				me.regulatoryMethod = method;
				win.close();
				me.addNewOmicSubmittingPanel("regulatoryomic");
			};
		};
		var win = Ext.create('Ext.window.Window', {
			title: 'Regulatory Omic — choose analysis method',
			modal: true,
			width: 720,
			closable: true,
			bodyPadding: 14,
			layout: { type: 'hbox', align: 'stretch' },
			defaults: { flex: 1, margin: 6, bodyPadding: 12, border: 1 },
			items: [{
				xtype: 'panel',
				title: 'Pairwise',
				html: '<p style="min-height: 130px;">Analyse <b>one regulatory omic at a time</b>. ' +
					'Independent correlation between each regulator and its target gene. ' +
					'Use this for the classical miRNA-target style of analysis. ' +
					'You can add several Pairwise panels (one per regulatory omic) in the same job.</p>',
				bbar: ['->', { xtype: 'button', text: 'Choose Pairwise', handler: pickHandler('pairwise') }]
			}, {
				xtype: 'panel',
				title: 'MORE',
				html: '<p style="min-height: 130px;">Joint <b>multi-omic regression</b> (PLS / MLR) over one or ' +
					'more regulators at once, filtered by VIP, &alpha; and R&sup2;. Use this when you want ' +
					'all regulators integrated into a single model. Only one MORE panel is allowed per job; ' +
					'use the &ldquo;+ Add another Regulatory Omic&rdquo; button inside the panel to stack regulators.</p>',
				bbar: ['->', { xtype: 'button', text: 'Choose MORE', handler: pickHandler('more') }]
			}]
		});
		win.show();
	};
	/**
	* This function adds a new OmicSubmittingPanel for the given type.
	* @param {string} type for the new omic panel.
	*/
	this.addNewOmicSubmittingPanel = function(type) {
		var newElem, submitForm;

		if (type === "geneexpression") {
			newElem = new OmicSubmittingPanel(this.nFiles, {
				type: "Gene expression",
				fileType: "Gene Expression file",
				relevantFileType: "Relevant Genes list"
			});
		} else if (type === "proteomics") {
			newElem = new OmicSubmittingPanel(this.nFiles, {
				type: "Proteomics",
				fileType: "Proteomic quatification",
				relevantFileType: "Relevant proteins list",
				featureEnrichment: "features"
			});
		} else if (type === "metabolomics") {
			newElem = new OmicSubmittingPanel(this.nFiles, {
				type: "Metabolomics",
				fileType: "Metabolomic quatification",
				relevantFileType: "Relevant Compound list",
				featureEnrichment: "features"
			});
		} else if (type === "mirnaseq") {
			newElem = new OmicSubmittingPanel(this.nFiles, {
				type: "miRNA-seq",
				fileType: "miRNA-Seq quatification",
				relevantFileType: "Relevant miRNA-Seq list"
			});
		} else if (type === "dnaseseq") {
			newElem = new OmicSubmittingPanel(this.nFiles, {
				type: "DNase-seq",
				fileType: "DNAse-Seq quatification",
				relevantFileType: "Relevant DNAse-Seq list"
			});
		} else if (type === "mirnabasedomic") {
			// Legacy entry point — kept for restore-from-saved-job paths.
			newElem = new MiRNAOmicSubmittingPanel(this.nFiles);
			if (this.regulatoryMethod === null) { this.regulatoryMethod = "pairwise"; }
		} else if (type === "bedbasedomic") {
			newElem = new RegionBasedOmicSubmittingPanel(this.nFiles);
		} else if (type === "otheromic") {
			newElem = new OmicSubmittingPanel(this.nFiles);
		} else if (type === "moreanalysis") {
			// Legacy entry point — kept for restore-from-saved-job paths.
			newElem = new MORESubmittingPanel(this.nFiles);
			if (this.regulatoryMethod === null) { this.regulatoryMethod = "more"; }
		} else if (type === "regulatoryomic") {
			// Unified Regulatory Omic entry. First click opens the chooser;
			// subsequent clicks route to the locked method.
			if (this.regulatoryMethod === null) {
				this.showRegulatoryMethodChooser();
				return null;
			}
			if (this.regulatoryMethod === "pairwise") {
				newElem = new MiRNAOmicSubmittingPanel(this.nFiles, { regulatoryMethod: "pairwise" });
			} else {
				// MORE: enforce a single MORE panel per job (joint analysis only).
				var existingMore = this.getComponent().queryById("submittingPanelsContainer")
					.query("container[cls=omicbox moreBasedOmic]");
				if (existingMore.length > 0) {
					showInfoMessage("MORE Analysis", {
						message: "You already have a MORE panel in this job. Use the " +
							"&ldquo;+ Add another Regulatory Omic&rdquo; button inside it to add more regulators.",
						showButton: true
					});
					return null;
				}
				newElem = new MORESubmittingPanel(this.nFiles);
			}
		} else if (type == "transcriptionfactor") {
			newElem = new OmicSubmittingPanel(this.nFiles, {
				type: "Transcription factor",
				fileType: "Transcription factor file",
				relevantFileType: "Relevant Genes list"
			});
		}
		newElem.setParent(this);

		submitForm = this.getComponent().queryById("submittingPanelsContainer");
		submitForm.insert(1, newElem.getComponent()).focus();

		// The Regulatory Omic card stays clickable in Pairwise mode (multi-add)
		// but is hidden once a MORE panel exists (single-panel rule).
		var keepCardVisible = (
			type === "otheromic" || type === "bedbasedomic" || type === "mirnabasedomic" ||
			(type === "regulatoryomic" && this.regulatoryMethod === "pairwise")
		);
		if (!keepCardVisible) {
			$("div.availableOmicsBox[title=" + type + "]").css("display", "none");
		}

		if (submitForm.items.getCount() > 2) {
			$(".dragHerePanel").fadeOut();
		}

		this.nFiles++;

		return newElem;
	};
	/**
	* This function removes a given omicSubmittingPanel and restores the omic type
	* at the availableOmics panel.
	*
	* @param {OmicSubmittingPanel} omicSubmittingPanel
	*/
	this.removeOmicSubmittingPanel = function(omicSubmittingPanel) {
		var submitForm = this.getComponent().queryById("submittingPanelsContainer");
		submitForm.remove(omicSubmittingPanel.getComponent());

		var removedType = omicSubmittingPanel.type;
		if (!this.exampleMode) {
			if (removedType === "moreanalysis") {
				// MORE panel removed — free up the unified Regulatory Omic card again.
				$("div.availableOmicsBox[title=regulatoryomic]").fadeIn();
			} else if (removedType !== undefined &&
				removedType !== "otheromic" && removedType !== "bedbasedomic" &&
				removedType !== "mirnabasedomic") {
				$("div.availableOmicsBox[title=" + removedType + "]").fadeIn();
			}
		}

		// Auto-unlock regulatory method when no Regulatory Omic panels remain,
		// so the user can pick a different method on their next add.
		var remainingRegulatory = submitForm.query(
			"container[cls=omicbox miRNABasedOmic],[cls=omicbox moreBasedOmic]"
		);
		if (remainingRegulatory.length === 0) {
			this.regulatoryMethod = null;
		}

		if (submitForm.items.getCount() === 2 && !this.exampleMode) {
			$(".dragHerePanel").fadeIn();
		}

		delete omicSubmittingPanel;
	};
	/**
	* Opens the "Load example" picker, populated from the server's catalogue.
	*
	* The catalogue lives in examplefiles/datasets/manifest.json and is the
	* single source of truth for which examples exist. Nothing about the
	* scenarios is hardcoded here: adding one to the manifest makes it appear.
	*
	* Every pipeline is listed, not just pathway-acquisition. The region,
	* miRNA and MORE examples are pre-processing steps that feed this same form,
	* and setExampleModeHandler creates the one panel each of them needs -- so
	* they are reachable here rather than only by hand-typing a URL. MORE in
	* particular had no example at all before, which is why its input format
	* (per-sample matrices plus a numeric design matrix, unlike every other
	* omic) was undocumented by example.
	*/
	this.showExampleChooser = function() {
		var me = this;

		$.ajax({
			url: SERVER_URL_EXAMPLE_DATASETS,
			type: "GET",
			dataType: "json"
		}).done(function(response) {
			var scenarios = (response && response.scenarios) ? response.scenarios : [];

			if (scenarios.length === 0) {
				// The server has no catalogue -- an incomplete deploy. Fall back
				// to the default rather than leaving the button dead: the
				// servlet resolves "example" with no id on its own.
				me.setExampleModeHandler(null);
				return;
			}
			me.renderExampleChooser(scenarios, response.defaultScenario);
		}).fail(function() {
			// Same reasoning: a failed catalogue request must not remove the
			// ability to load an example.
			me.setExampleModeHandler(null);
		});
	};
	/**
	* Draws the picker. Split from the fetch so the layout can be reasoned
	* about (and changed) without touching the request handling.
	*/
	this.renderExampleChooser = function(scenarios, defaultScenarioId) {
		var me = this;

		// Grouped by pipeline, because the groups behave differently once
		// loaded: the first submits straight to the pathway analysis, the rest
		// run a conversion step first.
		var GROUPS = [
			["pathway-acquisition", "Multi-omic pathway analysis",
			 "Loads straight into the form below and runs the pathway analysis."],
			["mirna2genes", "Regulatory omics — pairwise",
			 "Pairs each regulator with its target genes first, then runs the analysis."],
			["more", "Regulatory omics — MORE",
			 "Fits a joint multi-omic regression over per-sample data, then runs the analysis."],
			["regions2genes", "Region-based omics",
			 "Assigns genomic regions to genes with RGmatch first, then runs the analysis."]
		];

		var makeCard = function(scenario) {
			var badge = scenario.simulated
				? '<span style="background:#E8F1FA;color:#2F73BC;border-radius:3px;' +
				  'padding:1px 6px;font-size:11px;">simulated</span>'
				: '<span style="background:#FDF0E6;color:#B4690E;border-radius:3px;' +
				  'padding:1px 6px;font-size:11px;">real data</span>';

			var facts = [];
			if (scenario.omicNames && scenario.omicNames.length) {
				facts.push('<b>' + scenario.omicNames.length + '</b> omic' +
					(scenario.omicNames.length === 1 ? '' : 's') +
					': ' + scenario.omicNames.join(', '));
			}
			if (scenario.conditions && scenario.conditions.length) {
				facts.push('<b>' + scenario.conditions.length + '</b> condition' +
					(scenario.conditions.length === 1 ? '' : 's'));
			}
			if (scenario.databases && scenario.databases.length) {
				facts.push(scenario.databases.join(' + '));
			}

			var tests = (scenario.tests || []).map(function(item) {
				return '<li>' + Ext.String.htmlEncode(item) + '</li>';
			}).join('');

			return {
				xtype: 'panel',
				title: scenario.title,
				bodyPadding: 12,
				margin: '0 0 10 0',
				border: 1,
				html: '<p style="margin:0 0 8px 0;">' + badge + '</p>' +
					'<p style="margin:0 0 8px 0;">' +
					Ext.String.htmlEncode(scenario.summary) + '</p>' +
					'<p style="margin:0 0 6px 0;color:#6B6B6B;font-size:12px;">' +
					facts.join(' &nbsp;•&nbsp; ') + '</p>' +
					(tests ? '<p style="margin:0 0 2px 0;font-size:12px;">' +
						'<b>Exercises:</b></p><ul style="margin:0;font-size:12px;' +
						'color:#6B6B6B;">' + tests + '</ul>' : ''),
				bbar: ['->', {
					xtype: 'button',
					text: scenario.id === defaultScenarioId ? 'Load (default)' : 'Load',
					handler: function() {
						win.close();
						me.setExampleModeHandler(scenario);
					}
				}]
			};
		};

		var items = [{
			xtype: 'box',
			html: '<p style="margin:0 0 12px 0;">Each dataset exercises a ' +
				'different part of PaintOmics. The <b>real data</b> entries are ' +
				'the published STATegra time course; the <b>simulated</b> ones ' +
				'carry a known signal planted into real KEGG pathways, so you ' +
				'can check that the analysis recovers what was put in.</p>'
		}];

		GROUPS.forEach(function(group) {
			var pipeline = group[0], heading = group[1], note = group[2];
			var inGroup = scenarios.filter(function(s) { return s.pipeline === pipeline; });
			if (inGroup.length === 0) { return; }

			items.push({
				xtype: 'box',
				html: '<h4 style="margin:14px 0 2px 0;">' + heading + '</h4>' +
					'<p style="margin:0 0 8px 0;color:#6B6B6B;font-size:12px;">' +
					note + '</p>'
			});
			inGroup.forEach(function(scenario) { items.push(makeCard(scenario)); });
		});

		var win = Ext.create('Ext.window.Window', {
			title: 'Load example — choose a dataset',
			modal: true,
			width: 760,
			maxHeight: 660,
			closable: true,
			bodyPadding: 14,
			autoScroll: true,
			items: items
		});
		win.show();
	};
	/**
	* Configures the form for a chosen example dataset.
	*
	* @param {Object|null} scenario an entry from /example_datasets, or null to
	*        let the server pick its default (used when the catalogue is
	*        unreachable, so the button still works on an incomplete deploy).
	*/
	this.setExampleModeHandler = function(scenario) {
		var omicSubmittingPanels;
		this.exampleMode = true;
		this.exampleScenarioId = scenario ? scenario.id : null;
		this.examplePipeline = (scenario && scenario.pipeline) || "pathway-acquisition";

		var speciesCombo = this.getComponent().queryById("speciesCombobox");
		speciesCombo.setValue(scenario && scenario.organism ? scenario.organism : "mmu");
		speciesCombo.setReadOnly(true);

		// The databases are NOT taken from the scenario. setValue above has
		// already fired the combo's change listener, so applyDatabaseAvailability
		// has ticked whatever this server installed for the dataset's organism --
		// and that is what PathwayAcquisitionServlet will run, because its example
		// branch resolves the same way and overrides the manifest.
		//
		// The manifest's `databases` is a property of the dataset as authored and
		// cannot know what the host running it installed. Five of the seven
		// bundled scenarios declare KEGG alone while every one of them is mmu, an
		// organism that ships with Reactome, so honouring it meant an example ran
		// against half the pathways the same files would reach as an upload.

		// "~=", not "=". ComponentQuery's "=" compares the WHOLE cls string, and
		// only the plain omic panel declares cls:"omicbox" on its own; the region
		// ("omicbox regionBasedOmic"), miRNA ("omicbox miRNABasedOmic") and MORE
		// ("omicbox moreBasedOmic") panels never matched and therefore survived
		// this clear-out into the next example -- loading MORE and then a gene
		// dataset left the MORE panel sitting above the new omics and submitted it.
		// "~=" tests one entry of the whitespace-separated list, which is what the
		// cls attribute actually is.
		omicSubmittingPanels = this.getComponent().queryById("submittingPanelsContainer").query("[cls~=omicbox]");
		for (var i in omicSubmittingPanels) {
			$("#" + omicSubmittingPanels[i].el.id + " a.deleteOmicBox").click();
		}

		var me = this;
		var pipeline = (scenario && scenario.pipeline) || "pathway-acquisition";

		if (pipeline === "pathway-acquisition") {
			// One panel per omic the dataset actually contains, in the order the
			// manifest lists them. Previously this was a fixed list of six, so
			// a dataset with a different composition showed the wrong form.
			var omicNames = (scenario && scenario.omicNames) ||
				["Transcription factor", "miRNA-seq", "DNase-seq", "Proteomics",
				 "Metabolomics", "Gene expression"];
			omicNames.forEach(function(omicName) {
				var panel = me.addNewOmicSubmittingPanel(examplePanelTypeFor(omicName));
				if (panel) { panel.setExampleMode(omicName); }
			});
		} else {
			// A pre-processing pipeline: regions-to-genes, miRNA-to-genes or
			// MORE. These take ONE panel, and submitting it posts to that
			// pipeline's own endpoint first; its output then feeds the normal
			// pathway analysis. submitFormHandler already routes on the panel's
			// css class, so creating the right panel is the whole wiring.
			//
			// MORE additionally needs its method locked, because the unified
			// "Regulatory Omic" card would otherwise open the method chooser.
			if (pipeline === "more") { me.regulatoryMethod = "more"; }
			var panel = me.addNewOmicSubmittingPanel(EXAMPLE_PANEL_FOR_PIPELINE[pipeline]);
			if (panel && panel.setExampleMode) {
				panel.setExampleMode(scenario);
			}
		}

		$("#availableOmicsContainer").css("display", "none");
		// The button used to hide itself here, so a second dataset could only be
		// reached by throwing the whole job away with Reset. Loading an example is
		// not a one-way door -- the clear-out above is the first thing this
		// function does -- so it stays, renamed for what it now does.
		$("#exampleButton").html('<i class="fa fa-file-text-o"></i> Load another example');

		// Deliberately NOT ticking the AI consent checkbox. It is a permission to
		// send pathway summaries, feature lists and the experiment design text to
		// a third-party LLM service, and the server reads it straight off this
		// form on the example branch too (PathwayAcquisitionServlet
		// setAIConsent(formFields.get("aiConsent", "false"))). The dataset being
		// public says nothing about whether the user wants that call made on their
		// behalf, and clicking "Load example" is not an answer to the question the
		// checkbox asks. Note this neither ticks nor unticks it: on a local
		// instance DEFAULT_AI_CONSENT_ENABLED has already ticked it and loading an
		// example leaves that alone, which is the intent both ways round.
		var expDesign = this.getComponent().down('[name=experimentDesign]');
		if (expDesign && scenario) {
			expDesign.setValue(exampleExperimentDesignFor(scenario));
		} else if (expDesign) {
			expDesign.setValue(STATEGRA_EXPERIMENT_DESIGN);
		}

		this.lockFormForExample(pipeline);

		// Inside the callback, so the "Databases" line names the databases the
		// job will really run rather than the ones the manifest declares. It used
		// to print the manifest's list, which after this change would understate
		// every mmu example by leaving Reactome out of a run that includes it.
		this.applyDatabaseAvailability(function(databases) {
			var facts = scenario
				? '<ul>' +
					'<li><b>Dataset:</b> ' + Ext.String.htmlEncode(scenario.title) + '</li>' +
					'<li><b>Organism:</b> ' + Ext.String.htmlEncode(scenario.organism || "mmu") + '</li>' +
					'<li><b>Omics:</b> ' + Ext.String.htmlEncode((scenario.omicNames || []).join(', ')) + '</li>' +
					'<li><b>Conditions:</b> ' + ((scenario.conditions || []).length || 1) + '</li>' +
					'<li><b>Databases:</b> ' + Ext.String.htmlEncode(databases.join(', ')) + '</li>' +
					'</ul>' +
					(scenario.simulated
						? '<p>This dataset is <b>simulated</b>: a known signal was planted ' +
						  'into real KEGG pathways. The pathways the enrichment should rank ' +
						  'highest are listed alongside the files, so you can check that ' +
						  'the analysis recovers them.</p>'
						: '<p>This is <b>real published data</b> (STATegra).</p>')
				: '<p>The bundled example dataset was loaded.</p>';

			showInfoMessage("About this example", {
				message: facts,
				showButton: true,
				height: 300
			});
		});
	};

	/**
	* Ticks every pathway database installed for `organism` and locks the rest.
	*
	* This is the whole of the rule: a database that is installed is selected,
	* because there is no reason to analyse against half of what the server has;
	* a database that is not installed cannot be selected, because
	* PathwayAcquisitionServlet would drop it and the analysis has no pathways to
	* run it against. Both halves used to be wrong in the same direction -- all
	* three boxes were always offered, Reactome was pre-ticked on localhost and
	* nowhere else, and the two that did not apply were silently discarded.
	*
	* KEGG is skipped: its box is ticked and disabled from birth and the server
	* unions it into every job regardless.
	*
	* Asynchronous because the availability map may still be in flight; ordering
	* is safe without a guard because it reads the combo's value at apply time
	* rather than closing over the organism it was called for, so two overlapping
	* calls converge on the same answer instead of racing.
	*
	* @param {Function} done optional, called with the applied database list.
	*/
	this.applyDatabaseAvailability = function(done) {
		var me = this;
		loadOrganismDatabases().then(function() {
			var combo = me.getComponent().queryById("speciesCombobox");
			var organism = combo ? combo.getValue() : null;
			var installed = getInstalledDatabasesFor(organism);
			var applied = ["KEGG"];

			Ext.each(["MapMan", "Reactome"], function(database) {
				var box = me.getComponent().queryById(database.toLowerCase() + "DB");
				if (!box) { return; }

				// null means the map never arrived: offer the box rather than
				// hiding a database the server may well have.
				var available = (installed === null) ||
					(Ext.Array.indexOf(installed, database) !== -1);

				// setValue before setDisabled. A disabled checkbox is excluded
				// from getSubmitData(), so leaving a stale tick on a disabled box
				// would show a database as selected that could never be posted.
				box.setValue(available);
				box.setDisabled(!available);
				if (box.setBoxLabel) {
					box.setBoxLabel(available
						? database
						: database + ' <span style="color:#8A8A8A;">(not installed for this organism)</span>');
				}
				if (available) { applied.push(database); }
			});

			me.describeDatabaseAvailability(organism, installed, applied);
			if (done) { done(applied); }
		});
	};

	/**
	* Replaces the note under the checkboxes with what is true for this organism.
	*
	* The note it replaces said "for some species more than one database might be
	* available" and left the reader to find out which by ticking a box and
	* reading the results.
	*/
	this.describeDatabaseAvailability = function(organism, installed, applied) {
		var note = this.getComponent().queryById("databasesAvailabilityNote");
		if (!note || !note.update) { return; }

		var reference = ' Please check <b><a href="https://paintomics.readthedocs.io/en/latest/1_4_id/"' +
			' target="_blank">Supported ID and databases</a></b>.';
		var message;

		if (!organism) {
			message = ' Choose an organism to see which pathway databases are available for it.';
		} else if (installed === null) {
			message = ' The list of installed databases could not be read from the server,' +
				' so all of them are offered; any that this server cannot run for ' +
				Ext.String.htmlEncode(organism) + ' will be left out of the analysis.';
		} else {
			message = ' <b>' + Ext.String.htmlEncode(applied.join(' + ')) + '</b> ' +
				(applied.length > 1 ? 'are' : 'is') + ' installed for ' +
				Ext.String.htmlEncode(organism) + ' and included by default.';
			message += ' Untick a database to leave it out.';
		}

		note.update('<span class="infoTip" style=" font-size: 12px; margin: 0 26px 10px 196px;">' +
			message + reference + '</span>');
	};

	/**
	* Shows the loaded example for what it is: a fixed dataset, not a draft.
	*
	* The composition of an example job is decided on the server. For a
	* pathway-acquisition dataset the client posts a scenario id and
	* pathwayAcquisitionStep1_PART1 rebuilds the omic list, the organism and the
	* databases from examplefiles/datasets/manifest.json, ignoring every omic
	* field in this form; the pre-processing pipelines do the same in their own
	* servlets (applyScenario / applyMoreScenario). So the form was decorative
	* and did not say so: deleting the Metabolomics panel and pressing Run
	* produced a job byte-identical to an untouched one, and the progress dialog
	* still announced "mapping Metabolomics".
	*
	* Locking it is the honest half of the fix. Making the server honour the
	* edits is the other half and is not done here -- see the handoff note.
	*
	* Nothing here uses setDisabled(): a disabled field returns null from
	* getSubmitData() and never reaches the server, and the chained pipelines
	* (regions2genes, mirna2genes, more) DO post this form for real once their
	* conversion has run -- their step 1 is an ordinary upload, which is why
	* step1OnFormSubmitHandler refuses the example endpoint for them. setReadOnly
	* keeps every value on the wire while removing the invitation to change it.
	*
	* @param {string} pipeline the loaded scenario's pipeline.
	*/
	this.lockFormForExample = function(pipeline) {
		var container = this.getComponent().queryById("submittingPanelsContainer");
		var panels = container.query("[cls~=omicbox]");
		var fields, i, j;

		for (i = 0; i < panels.length; i++) {
			fields = panels[i].query("field");
			for (j = 0; j < fields.length; j++) {
				if (fields[j].setReadOnly) {
					fields[j].setReadOnly(true);
				}
			}
			// The trash icon is the most misleading control on the page: it
			// removes the panel and changes nothing about what runs. Hidden
			// rather than unbound, because the clear-out in
			// setExampleModeHandler still triggers this handler by jQuery when a
			// second example is loaded over this one.
			if (panels[i].getEl()) {
				$(panels[i].getEl().dom).find("a.deleteOmicBox").css("display", "none");
			}

			// MORE's "+ Add another Regulatory Omic" builds a block that the
			// example endpoint never reads: MOREServlet returns right after
			// applyMoreScenario, which takes every regulator from the manifest.
			var addOmicWrapper = panels[i].queryById("addOmicWrapper");
			if (addOmicWrapper) { addOmicWrapper.setVisible(false); }
		}

		// CheckboxGroup.setReadOnly forwards to each box, and Checkbox.setReadOnly
		// only marks the DOM input disabled -- the component stays enabled, so the
		// values still travel. That matters: for a chained example, step 1 is a
		// real upload and these boxes are the only place the databases come from.
		var databases = this.getComponent().queryById("databasesCheckboxGroup");
		if (databases && databases.setReadOnly) {
			databases.setReadOnly(true);
		}

		// Rebuilt rather than kept, so it sits above the panels of the example
		// that is loaded now: new panels are inserted at index 1 as well.
		var note = container.queryById("exampleFixedNote");
		if (note) { container.remove(note); }
		container.insert(1, {
			xtype: "box",
			itemId: "exampleFixedNote",
			html: '<p style="margin:0 0 10px 0;padding:8px 12px;border-left:4px solid var(--pa-accent-blue);' +
				'background:rgba(38,132,255,0.08);font-size:12px;line-height:1.5;">' +
				'<b>This example dataset is fixed.</b> Its omics, organism and databases come from ' +
				'the server&rsquo;s example catalogue' +
				(pipeline === "pathway-acquisition" ? "" : " for this pre-processing step") +
				', so the panels below are shown read-only: changes made here would not reach the ' +
				'analysis. Press <b>Reset</b> to go back to an upload form, or ' +
				'<b>Load another example</b> to switch dataset.</p>'
		});
	};

	/**
	* This function is called when the user press the "Run Paintomics" button.
	* First we get all the RegionBasedOmic panels.
	* If there is one or more panel which contains to-be-processed BED files then
	* we send first those panels to server for processing "step1SubmitRegionBasedOmics".
	*
	* If there is not RegionBasedOmic panels or they contain already processed files
	* then we call to normal execution "step1OnFormSubmitHandler".
	*
	*/
	this.submitFormHandler = function() {
		var aux, omicBoxes;

		omicBoxes = this.getComponent().queryById("submittingPanelsContainer").query("container[cls=omicbox regionBasedOmic],[cls=omicbox miRNABasedOmic],[cls=omicbox moreBasedOmic]");
		for (var i = omicBoxes.length; i--;) {
			aux = omicBoxes[i].queryById("itemsContainer");
			if (aux === null || aux.isDisabled()) {
				omicBoxes.splice(i, 1);
			}
		}

		if (omicBoxes.length > 0) {
			this.controller.step1ComplexFormSubmitHandler(this, omicBoxes);
		} else {
			this.controller.step1OnFormSubmitHandler(this);
		}
	};
	/**
	* This function checks the validity for each OmicSubmittingPanel
	*
	* @returns Boolean
	*/
	this.checkForm = function() {
		var items, valid, emptyFields;

		items = this.getComponent().query("container[cls=omicbox], container[cls=omicbox regionBasedOmic],[cls=omicbox miRNABasedOmic],[cls=omicbox moreBasedOmic]");
		valid = this.getComponent().queryById("speciesCombobox").isValid();
		for (var i in items) {
			valid = valid && items[i].isValid();
		}

		emptyFields = 0;
		for (var i in items) {
			if (items[i].isEmpty() === true) {
				emptyFields++;
				$(items[i].getEl().dom).find("a.deleteOmicBox").click();
			}
		}

		return valid && (emptyFields < items.length);
	};

	//    this.showMyDataPanel = function () {
	//        this.controller.showMyDataPanelClickHandler(this);
	//    };

	this.initComponent = function() {
		var me = this;
		this.component = Ext.widget({
			xtype: "container",
			minHeight: 800,
			padding: '10',
			items: [
				{
				xtype: "box",
				cls: "toolbar secondTopToolbar",
				html:
				'<a class="button btn-danger btn-right" id="resetButton"><i class="fa fa-refresh"></i> Reset</a>' +
				'<a class="button btn-success btn-right" id="submitButton"><i class="fa fa-play"></i> Run PaintOmics</a>' +
				'<a class="button btn-secondary btn-right" id="exampleButton"><i class="fa fa-file-text-o"></i> Load example</a>'
			}, {
					xtype: 'box',
					cls: "contentbox",
					/* The page column is already capped and centred by --pa-page-max
					   on #mainViewCenterPanel. Capping the card again at 1300 left a
					   100px dead strip down the right of every block on this page,
					   so the three cards read as pushed to one side. */
					style: "margin-top:50px",
					html: '<div class="po-hero-section">' +
						'<div class="po-hero">' +
							'<div class="po-hero-text">' +
								'<div class="po-hero-badge">Multi-Omics Integration Platform</div>' +
								'<h1>PaintOmics AI <span>' + APP_VERSION + '</span></h1>' +
								'<p class="po-hero-desc">Integrative visualization of multiple omic datasets onto KEGG, Reactome, and MapMan biological pathway maps across multiple species and biological kingdoms.</p>' +
								'<div class="po-hero-ai-highlight">' +
									'<div><span class="po-ai-icon">' + getAIMark(15) + '</span> <strong>AI-Powered Pathway Interpretation</strong></div>' +
									'<p>Turns your ranked pathways into a written interpretation: it reads the cross-omic patterns, finds the supporting literature, and drafts the biology with citations you can check.</p>' +
								'</div>' +
								'<div class="po-hero-actions">' +
									'<a href="http://paintomics.readthedocs.org/en/latest/" target="_blank" class="po-btn-primary">Documentation</a>' +
									'<a href="https://github.com/ConesaLab/paintomics4/" target="_blank" class="po-btn-outline">GitHub</a>' +
									'<a href="mailto:paintomics4@gmail.com" class="po-btn-outline">Contact</a>' +
								'</div>' +
							'</div>' +
							'<div class="po-hero-visual">' +
								PO_HERO_FLOW_SVG +
								'<a href="javascript:void(0)" id="graphicalAbstract" class="po-hero-flow-link">View the full graphical abstract</a>' +
							'</div>' +
						'</div>' +
					'</div>'
			}, {
				xtype: 'box',
				cls: "contentbox po-about-section",
				style: "margin-top:4px",
				html: '<div id="about">' +
					'<h2>How it works</h2>' +
					'<div class="po-steps-grid">' +
						'<div class="po-step-card">' +
							'<div class="po-step-number">1</div>' +
							// Not "Data uploading": the upload form's own section heading
							// two cards below is exactly that, and the two sat on one
							// screen saying the same words about different things. This
							// card is the whole of step 1, of which uploading is the
							// fourth of five actions it lists.
							'<h3>Upload and run</h3>' +
							'<ol>' +
								'<li>Choose your organism.</li>' +
								// "untick any you want to leave out" was not true of KEGG, which is
								// rendered `checked: true, disabled: true` and labelled "KEGG
								// (required)" - the server adds it regardless. Telling someone to
								// untick a box that cannot be unticked sends them looking for a
								// broken control.
								'<li>Check the pathway databases: KEGG is always included, and every other database installed for your organism is ticked by default, so untick any of those you want to leave out.</li>' +
								'<li>Decide whether to enable the AI interpretation, and describe your experiment design if you do.</li>' +
								'<li>Upload your multi-omic data, or load an example (<a class="button btn-secondary btn-inline btn-small" href="javascript:void(0)"><i class="fa fa-file-text-o"></i> Load example</a>) to explore PaintOmics with a ready-made dataset.</li>' +
								'<li>Click on <a class="button btn-success btn-inline btn-small" href="javascript:void(0)"><i class="fa fa-play"></i> Run PaintOmics</a> button.</li>' +
							'</ol>' +
						'</div>' +
						'<div class="po-step-card">' +
							'<div class="po-step-number">2</div>' +
							'<h3>Identifier and name matching</h3>' +
							'<p>PaintOmics requires Entrez IDs for working with KEGG, Reactome and MapMan biological pathway maps, so the tool will convert the names and identifiers from different sources and databases in your input data. This screen shows the number of features successfully mapped and the data distribution used for pathway colouring. Metabolite name assignments are shown, and you can choose which one to keep when a name is ambiguous. Click <a class="button btn-success btn-inline btn-small" href="javascript:void(0)"><i class="fa fa-play"></i> Next step</a> when you are ready.</p>' +
						'</div>' +
						'<div class="po-step-card">' +
							'<div class="po-step-number">3</div>' +
							'<h3>Explore results</h3>' +
							'<p>You get a Pathways summary, a classification, a network and an enrichment analysis. Paint any of the listed pathways with <a href="javascript:void(0)" class="button btn-inline btn-small" style="background-color:#756C6C;font-size:14px;color:#fff;"><i class="fa fa-paint-brush"></i></a>, or ask for an <b>AI-powered pathway interpretation</b> with <a href="javascript:void(0)" class="button btn-inline btn-small" style="background-color:#2F73BC;font-size:14px;color:#fff;">' + getAIMark(14) + ' AI Interpret</a>. Read more about these analyses in <a href="http://paintomics.readthedocs.io/en/latest/" target="_blank">our documentation</a>.</p>' +
						'</div>' +
					'</div>' +
					'<h2 style="margin-top:24px;">Video tutorials</h2>' +
					'<div class="po-tutorials-grid">' +
						'<iframe width="560" height="315" src="https://www.youtube.com/embed/brvToUmL1n4" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>' +
						'<iframe width="560" height="315" src="https://www.youtube.com/embed/4XxPKqAubsA" title="YouTube video player" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>' +
					'</div>' +
					'<p style="margin-top:16px;">Check the <b><a href="http://paintomics.readthedocs.org/en/latest/" target="_blank">User guide</a></b> for further information. For questions, email <a href="mailto:paintomics4@gmail.com">paintomics4@gmail.com</a> or visit our <a href="https://github.com/ConesaLab/paintomics4/">GitHub page</a>.</p>' +
				'</div>'
			}, {
				xtype: 'form',
				/* The card inset belongs on the panel, not on its body: ExtJS sizes a
				   body to the panel's content box and writes an explicit width onto
				   it, so .contentbox's own horizontal margin pushed this body 20px
				   past its panel and the upload card finished further right than the
				   two cards above it. */
				cls: "paStep1Form",
				margin: '0 10 0 10',
				bodyCls: "contentbox",
				layout: {type: 'vbox', align: 'stretch'},
				defaults: {labelAlign: "right", border: false},
				items: [
					{xtype: "box", flex: 1, html:'<h2>Data uploading</h2><h3>1. Organism selection </h3>'},
					{xtype: "container", flex: 1, layout: {type: "hbox"}, items: [
						{
							xtype: "container", layout: { type: "vbox", align: "stretch" }, flex: 0.4, items: [
							{
								xtype: 'combo',fieldLabel: 'Organism', name: 'specie',
								/* 26px is --pa-card-inset: this field sits directly under
								   "1. Organism selection", so it has to start on the same
								   left edge as that heading. */
								style: "margin: 10px 10px 10px 26px;",
								flex: 1,
								maxWidth: 450,
								itemId: "speciesCombobox",
								allowBlank: false,
								forceSelection: true,
								emptyText: 'Please choose an organism',
								displayField: 'name',
								valueField: 'value',
								queryMode: 'local',
								labelWidth: 150,
								/* The database checkboxes below are a function of this field.
								   `change` rather than `select`: setValue() fires change and not
								   select, and setExampleModeHandler sets the organism that way. */
								listeners: {
									change: function() { me.applyDatabaseAvailability(); }
								},
								store: Ext.create('Ext.data.ArrayStore', {
									fields: ['name', 'value'],
									autoLoad: true,
									sortOnLoad: true,
									remoteSort: false,
									sorters: [{
							        property: 'name',
							        direction: 'ASC'
							    }],
									proxy: {
										type: 'ajax',
										url: SERVER_URL_GET_AVAILABLE_SPECIES,
										reader: {
											type: 'json',
											root: 'species',
											successProperty: 'success'
										}
									}
								})
							},
							{
								xtype: "box", flex: 1, html:
								'<span class="infoTip" style=" font-size: 12px; margin-left: 196px; margin-bottom: 10px;">'+
								' Not your organism? <a href="javascript:void(0)" id="newOrganismRequest" style="color: rgb(211, 21, 108);">Request a new organism</a>.' +
								'</span>'
							}]
						},
						{
							xtype: "container", layout: { type: "vbox", align: "stretch" }, flex: 0.5, items: [
							{
								xtype: "textfield",
								fieldLabel: "Enter a job description",
								allowBlank: true,
								name: 'jobDescription',
								style: "margin: 10px 26px 10px 20px;",
								labelWidth: 150,
								width: 650,
								flex: 0,
								maxLength: 100
							}
							]
						}
						]
					},
					/* Databases is a row of its own, not the second item of the right-hand
					   column. Stacked there it made that column about 110px taller than the
					   left one, and an hbox column is only as tall as its own content - so
					   everything under the organism combo, the whole left half of section 1,
					   was a hole of that size. As a row it sits under both columns, starts on
					   the same left edge as Organism, and the section now ends where its last
					   field ends. */
					{
						xtype: "container", layout: { type: "vbox", align: "stretch" }, items: [
						{
							xtype: 'checkboxgroup', fieldLabel: 'Databases',
							// Named so lockFormForExample can find it: in example mode
							// the databases are resolved on the server, not from here.
							itemId: "databasesCheckboxGroup",
							style: "margin: 4px 10px 10px 26px;",
							maxWidth: 650,
							allowBlank: false,
							columns: 2,
							disabled: false,
							labelWidth: 148,
							/* The boxes are fixed -- these are the three databases PaintOmics knows
							   how to draw a pathway from -- but which of them can be TICKED is not,
							   and is not knowable here: it depends on what this server installed for
							   the organism chosen above. So every optional box starts unticked and
							   disabled, and applyDatabaseAvailability turns on the ones that
							   /organism_databases reports for the selected organism.
							
							   They used to be permanently selectable, and two of the three were a
							   lie for nearly every organism: PathwayAcquisitionServlet has always
							   intersected the submitted selection with the databases the organism
							   actually has, so ticking MapMan for mouse or Reactome for tomato
							   changed nothing at all and said nothing about it. */
							items: [
									// Only for information, KEGG database is added always on server side
									{ boxLabel: 'KEGG (required)', name: 'databases[]', inputValue: 'KEGG', checked: true, disabled: true },
									/* itemId as well as id: queryById finds either, but two ids on one page
									   is a global, and the region/miRNA/MORE flows can rebuild this form. */
									{ boxLabel: 'MapMan', name: 'databases[]', inputValue: 'MapMan',
									  checked: false, disabled: true,
									  itemId: 'mapmanDB', id: 'mapmanDB'},
									{ boxLabel: 'Reactome', name: 'databases[]', inputValue: 'Reactome',
									  checked: false, disabled: true,
									  itemId: 'reactomeDB', id: 'reactomeDB'},
							]
						},
						{
							// Rewritten by applyDatabaseAvailability once an organism is known, so
							// this text is only ever seen before one is chosen.
							xtype: "box", itemId: "databasesAvailabilityNote", html:
							'<span class="infoTip" style=" font-size: 12px; margin: 0 26px 10px 196px;">'+
							' Choose an organism to see which pathway databases are available for it. Please check <b><a href="https://paintomics.readthedocs.io/en/latest/1_4_id/" target="_blank">Supported ID and databases</a></b>.' +
							'</span>'
						}
						]
					},
					/*{
							xtype: "container",
							layout: "hbox",
							flex: 1,
							items: [{
								xtype: "textfield", 
								fieldLabel: "Enter a job description", 
								allowBlank: true,
								name: 'jobDescription',
								style: "margin: 20px 20px;",
								labelWidth: 150,
								width: 450,
								flex: 0
							}]
					}*/,
					{   // AI Interpretation section
						xtype: "box", flex: 1,
						html: '<h3>' + getAIMark(17) + ' 2. AI-powered pathway interpretation (optional)</h3>'
					},
					{
						xtype: "container", layout: {type: 'hbox', align: 'stretch'}, cls: "po-ai-section-body",
						/* The callout spans the full card but its prose is capped at a reading
						   measure, so as one column it filled half the box and left the other
						   half blank. Two columns give the explanation its measure and put the
						   two controls in the space the prose cannot use. */
						items: [{
							xtype: "container", flex: 3, layout: "anchor",
							items: [
								{
									xtype: "box",
									/* This paragraph was written in the marketing register -- "revolutionary",
									   "breathtaking computational power", "Next-Generation Agentic AI
									   Swarm", "the world's most powerful Large Language Models". It sits
									   directly above a consent checkbox, which is the one place in this
									   application where the careful voice is not optional: someone
									   deciding whether to send their data somewhere needs to know what
									   happens to it, not how remarkable it is.

									   It was also wrong. It described a fleet of agents dynamically
									   selecting among frontier models; pipeline.py makes sequential
									   calls to the one model the server is configured for, with a retry
									   loop. #aiProviderInline is filled in from /ai_provider once that
									   answers, so the recipient is named here rather than described as
									   "external". */
									html: '<p style="color:#555;font-size:13px;margin:0 0 10px 0;line-height:1.55;">' +
										'PaintOmics can draft the write-up of your results. It takes the pathways your analysis ' +
										'ranked highest, searches PubMed and Europe PMC for relevant literature, and asks a large ' +
										'language model to explain what the cross-omic patterns mean. You get a draft interpretation ' +
										'with citations, which you are expected to check.' +
										'<span id="aiProviderInline" class="ai-provider-inline"></span>' +
										'</p>'
								},
								{
									xtype: 'checkboxfield',
									/* Both colours were written inline, which put them out of reach of
									   dark.css -- an inline style beats a stylesheet -- so this
									   sentence stayed #C44500 on the dark surface and measured 3.29:1
									   at 13px, under the 4.5:1 AA asks of body text. It is the one
									   line that says what leaves this server and who receives it,
									   which makes it the worst line in the product to have to squint
									   at. Stated as classes instead, so dark.css can restate them
									   with --pa-ai-consent-warn -- a token it already declared for
									   exactly this and had no way to apply. Same fix, same reason, as
									   .formMessage. */
									boxLabel: 'Enable AI pathway interpretation (<span class="ai-consent-warn">sends your pathway results and the values of the matched features to <span id="aiProviderName">an external AI service</span></span>) ' +
										'<i class="fa fa-exclamation-circle ai-gdpr-info-icon" id="aiGdprInfoIcon" title="Data privacy &amp; compliance \u2014 click to learn what data is sent"></i>',
									name: 'aiConsent', inputValue: 'true', uncheckedValue: 'false',
									/* Off everywhere but a local instance -- a pre-ticked consent
									   box is not consent. See LOCAL INSTANCE DEFAULTS in
									   ServerConfiguration.js for why localhost is the exception,
									   and the guard note on the Reactome box above for the typeof. */
									checked: typeof DEFAULT_AI_CONSENT_ENABLED !== "undefined" && DEFAULT_AI_CONSENT_ENABLED,
									listeners: {
										afterrender: function() {
											/* Names the recipient in the consent label and in the callout
											   above it. Both are on screen before anyone opens the notice,
											   and the label is the surface the design system requires to
											   carry the statement. */
											fillAIProvenance(document);
											setTimeout(function() {
												var icon = document.getElementById("aiGdprInfoIcon");
												if (!icon) return;
												icon.addEventListener("click", function(e) {
													e.preventDefault();
													e.stopPropagation();
													var existing = document.getElementById("aiGdprOverlay");
													if (existing) { existing.remove(); return; }
													var overlay = document.createElement("div");
													overlay.id = "aiGdprOverlay";
													overlay.className = "ai-gdpr-overlay";
													var disclaimer = document.createElement("div");
													disclaimer.id = "aiGdprDisclaimer";
													disclaimer.className = "ai-gdpr-disclaimer";
													disclaimer.innerHTML =
														'<div class="ai-gdpr-disclaimer-header">' +
														'  <strong>Data Privacy &amp; Compliance Notice</strong>' +
														'  <button class="ai-gdpr-close">&times;</button>' +
														'</div>' +
														'<div class="ai-gdpr-disclaimer-body">' +
																'  <p><strong>What this feature does:</strong> it sends a summary of your analysis to a large ' +
																'  language model, which returns a draft interpretation with citations. PaintOmics does not run ' +
																'  the model itself.</p>' +
																'  <p id="aiGdprWhere" class="ai-gdpr-where"></p>' +
																'  <div class="ai-gdpr-sent">' +
																'    <strong class="ai-gdpr-sent-title">\u26A0 What leaves this server:</strong>' +
																'    <ul style="margin:6px 0 0;padding-left:18px;">' +
																'      <li>Pathway names, identifiers and enrichment statistics (p-values)</li>' +
																'      <li>Names of the genes, proteins and metabolites matched in each pathway</li>' +
																'      <li><strong>The measured values of those features</strong>, with their condition and ' +
																'      timepoint labels &mdash; these are rows of the file you uploaded, not just summaries</li>' +
																'      <li>Your experiment design description, if you provided one</li>' +
																'    </ul>' +
																'    <p style="margin:8px 0 0;">Pathway and feature names are also sent to <strong>NCBI PubMed</strong> ' +
																'    and <strong>Europe PMC</strong> to find the literature the interpretation cites.</p>' +
																'  </div>' +
																'  <div class="ai-gdpr-notsent">' +
																'    <strong class="ai-gdpr-notsent-title">\u2705 What does not leave this server:</strong>' +
																'    <ul class="ai-gdpr-safe" style="margin:6px 0 0;padding-left:18px;">' +
																'      <li>The files you uploaded, as files</li>' +
																'      <li>Features that were not matched to one of the interpreted pathways</li>' +
																'      <li>Your login credentials or account information</li>' +
																'    </ul>' +
																'  </div>' +
																'  <hr>' +
																'  <p><strong>Before you enable this, check your data</strong></p>' +
																'  <p>Under <strong>GDPR Article 9</strong>, genetic and health data are a special category and ' +
																'  may not be processed without an explicit lawful basis. Under <strong>Article 5(1)(c)</strong>, ' +
																'  send only what the analysis needs.</p>' +
																'  <p id="aiGdprTransfer" class="ai-gdpr-transfer"></p>' +
																'  <p><strong style="color:#c62828;">\u26D4 Never submit:</strong></p>' +
																'  <ul class="ai-gdpr-unsafe">' +
																'    <li>Patient names, clinical record identifiers, or any other PII</li>' +
																'    <li>Protected Health Information (PHI) under HIPAA or the GDPR</li>' +
																'    <li>Raw sequencing reads from identifiable human subjects</li>' +
																'    <li>Rare genetic variants that could re-identify an individual</li>' +
																'    <li>Unpublished clinical trial data linked to patients</li>' +
																'  </ul>' +
																'  <p style="font-size:11px;color:#666;margin-top:8px;">' +
																'    By enabling this feature you confirm that the data you submit contains no personally ' +
																'    identifiable or special-category data as defined by GDPR Article 9, or that you have a ' +
																'    lawful basis for processing it. ' +
																'    For full details, see our <a href="conditions.html" target="_blank">Terms &amp; Conditions</a>.</p>' +
														'</div>';
													overlay.appendChild(disclaimer);
													document.body.appendChild(overlay);
													/* The notice does not exist until the icon is clicked, so its two
													   provenance paragraphs are filled here rather than at render. The
													   answer is already cached by this point in every realistic case. */
													fillAIProvenance(disclaimer);
													overlay.addEventListener("click", function(ev) {
														if (ev.target === overlay) { overlay.remove(); }
													});
													disclaimer.querySelector(".ai-gdpr-close").addEventListener("click", function() {
														overlay.remove();
													});
												});
											}, 200);
										}
									}
								}
							]
						}, {
							xtype: "container", flex: 2, margin: '0 0 0 32', layout: "anchor",
							items: [
								{
									/* Three things were wrong here, and the first hid the other two.
									
									   The placeholder read: e.g., "RNA-seq wildtype vs knockout mouse
									   liver, n=3 per group". ExtJS writes emptyText into a
									   placeholder="..." attribute, so the first embedded double quote
									   closed the attribute and everything after it was parsed as stray
									   markup -- on screen the hint was "e.g.," and nothing more. The
									   example is the useful half of a placeholder and nobody had ever
									   seen it. Curly quotes carry the same meaning through intact.
									
									   Then the label: labelWidth 150, right-aligned, inside a column
									   already narrowed by the callout beside it -- which left roughly
									   250px to compose prose in. It goes on top now and the input takes
									   the full column.
									
									   And 90px is three lines for free text describing an experiment.
									   It opens taller, and .po-exp-design lets it be dragged further. */
									xtype: "textarea", fieldLabel: "Experiment design (optional)",
									name: 'experimentDesign',
									labelAlign: 'top', anchor: '100%', height: 132,
									cls: 'po-exp-design',
									emptyText: 'e.g. RNA-seq of wildtype vs knockout mouse liver, 3 replicates per group, sampled at 24 h',
									maxLength: 2000
								},
								{
									xtype: "box", cls: 'po-exp-design-hint',
									html: 'Describe the comparison your data represents. The interpretation uses it '+
									      'to say which direction of change means what.'
								}
							]
						}]
					},
					{
						xtype: "box",
						html: '<h3>3. Choose the files to upload <a class="button btn-right btn-small" href="resources/paintomics_example_data.zip"><i class="fa fa-download"></i> Download example data</a></h3>'
					},
					{
						xtype: "container",
						cls: "po-step1-omics-row",
						/* The three columns were 250 + max 600 + max 300, which on a
						   1360px card left ~190px of the row unclaimed and stopped the
						   block short of the card's right edge.

						   Deliberately not align:'stretch': the selected-omic panels
						   carry flex:1, so a stretched column hands them the leftover
						   height and each omic's coloured header grows a 50px band of
						   empty colour under its title. */
						layout: {type: 'hbox'},
						items: [{
							xtype: "box",
							id: "availableOmicsContainer",
							minHeight: 400,
							width: 250,
							/* No padding on the outer side: the row already sits on the card
							   inset, so the drag sources start where the headings do. */
							padding: "10 0",
							html: '<h2 style="text-align:center;">Available omics</h2>' +
							'<div class="availableOmicsBox" title="geneexpression"><h4><a href="javascript:void(0)"><i class="fa fa-plus-circle"></i></a> Gene expression</h4></div>' +
							'<div class="availableOmicsBox" title="metabolomics"><h4><a href="javascript:void(0)"><i class="fa fa-plus-circle"></i></a> Metabolomics</h4></div>' +
							'<div class="availableOmicsBox" title="proteomics"><h4><a href="javascript:void(0)"><i class="fa fa-plus-circle"></i></a> Proteomics</h4></div>' +
							'<div class="availableOmicsBox" title="regulatoryomic"><h4><a href="javascript:void(0)"><i class="fa fa-plus-circle"></i></a> Regulatory Omic</h4></div>' +
							'<div class="availableOmicsBox" title="bedbasedomic"><h4><a href="javascript:void(0)"><i class="fa fa-plus-circle"></i></a> Region-based omic</h4></div>' +
							'<div class="availableOmicsBox" title="otheromic"><h4><a href="javascript:void(0)"><i class="fa fa-plus-circle"></i></a> Other omics</h4></div>'
						}, {
							xtype: "container",
							id: "submittingPanelsContainer",
							minHeight: 150,
							minWidth: 200,
							margin: 10,
							flex: 2,
							layout: {type: 'vbox',align: "stretch"},
							items: [
								{xtype: 'box',html: '<h2  style="text-align:center;">Selected omics</h2>'},
								{xtype: 'box',html: '<p class="dragHerePanel">Drag and drop here your selected <i>omics</i></p>'}
							]
						},
				   		{
							xtype: "container",
							id: "additionalInfoContainer",
							minHeight: 150,
							minWidth: 200,
							maxWidth: 340,
							/* Left margin only - it is the gutter. The right side is the card
							   inset, which the row already carries. */
							margin: "10 0 10 10",
							flex: 1,
							layout: {type: 'vbox',align: "stretch"},
							items: [
								{xtype: 'box',html: '<div class="content"><h5><i class="fa fa-info-circle" style="color: var(--pa-accent-blue); font-size: 50px;"></i> Help</h5><p>Drag <i>omics</i> from <b>Available omics</b> to <b>Selected omics</b>, or click the <i class="fa fa-plus-circle"  style="font-size: 18px;"></i> button.</p><p>Remove any you do not need with <i class="fa fa-trash" style="font-size: 18px;"></i>.</p><p>When you are done, click <b>Run PaintOmics</b> in the top-right corner.</p></div>'}
							]
						}]
					}					
				]
			}],
			listeners: {
				boxready: function() {
					$("#submitButton").click(function() {
						me.submitFormHandler();
					});
					$("#exampleButton").click(function() {
						me.showExampleChooser();
					});
					$("#resetButton").click(function() {
						me.resetViewHandler();
					});
					$("#addOtherDataButton").click(function() {
						me.addNewOmicSubmittingPanel();
					});
					$("#newOrganismRequest").click(function() {
						application.getController("DataManagementController").requestNewSpecieHandler();
					});

					$(".availableOmicsBox a").click(function(){
						var type = $(this).parents(".availableOmicsBox").first().attr("title");
						me.addNewOmicSubmittingPanel(type);
					});
			
					$("#graphicalAbstract").click(function(){
						var imageWindow = new Ext.Window({
							modal:true,
							border:false,
							plain:true,
							width: '80%',
							height: '90%',
							constrain:true,
							html:'<img style="margin: 0 auto;max-height:100%; max-width:100%;" src="resources/images/GraphicalAbstract.png" />',
							resizable:{preserveAspectRatio: true}
						});
						imageWindow.show();
					});

					var containers = [$("#availableOmicsContainer")[0], $("#submittingPanelsContainer-targetEl")[0]];

					//INITIALIZE THE DRAG AND DROP
					dragula(containers, {
						moves: function(el, container, handle) {
							// elements are always draggable by default
							return el.tagName !== "H5" && container.id !== "submittingPanelsContainer-targetEl";
						}
					}).on("drop", function(el, container, source) {
						if (container.id === "submittingPanelsContainer-targetEl") {
							var type = $(el).attr("title");
							me.addNewOmicSubmittingPanel(type);
						}
						this.cancel(true);
					});


					me.addNewOmicSubmittingPanel("metabolomics");
					me.addNewOmicSubmittingPanel("geneexpression");
				},
				beforedestroy: function() {
					me.getModel().deleteObserver(me);
				}
			}
		});

		return this.component;
	};

	return this;
}
PA_Step1JobView.prototype = new View();

function DefaultSubmittingPanel(nElem, options) {
	/*********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/
	this.getOmicName = function() {
		return this.omicName;
	};
	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	this.toogleContent = function(alternativeComponent="itemsContainerAlt") {
		var component = this.getComponent().queryById(alternativeComponent);
		var isVisible = component.isVisible();
		component.setVisible(!isVisible);
		component.setDisabled(isVisible);

		component = this.getComponent().queryById("itemsContainer");
		if (component) {
			component.setVisible(isVisible);
			component.setDisabled(!isVisible);
		}
		return this;
	};

	this.removeOmicSubmittingPanel = function() {
		this.getParent().removeOmicSubmittingPanel(this);
		return this;
	};
}
DefaultSubmittingPanel.prototype = new View;

function OmicSubmittingPanel(nElem, options) {
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	options = (options || {});

	this.title = "Other data type";
	this.namePrefix = "omic" + nElem;
	this.omicName = "";
	this.mapTo = "Gene";
	this.fileType = null;
	this.relevantFileType = null;
	this.featureEnrichment = "genes";

	this.class = "otherFileBox";

	/*IF THE TYPE WAS SPECIFIED (e.g. gene_expression)*/
	if (options.type !== undefined) {
		//TODO CAPITALIZE THE FIRST LETTER
		this.omicName = options.type;
		this.title = options.type;

		if (['Metabolomics'].indexOf(options.type) !== -1) {
			this.mapTo = "Compound";
		}

		this.fileType = options.fileType;
		this.relevantFileType = options.relevantFileType;
		this.type = this.title.replace(" ", "").toLowerCase();
		this.class = this.type + "FileBox";
		this.featureEnrichment = options.featureEnrichment || "genes";
	}
	/*********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/

	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	/**
	* Display-only: the fields are disabled and the server resolves the actual
	* files from the manifest. Only the labels are set here.
	*
	* This used to render `"example/" + this.type + "_example.tab"`, which named
	* a file that has never existed in any release -- so the form taught a
	* filename convention nothing on the server would recognise if a user copied
	* it. Naming the omic instead is honest about what is going on: the specific
	* files belong to the chosen dataset, not to this panel.
	*
	* @param {string} [omicName] the manifest's name for this omic.
	*/
	this.setExampleMode = function(omicName){
		var label = omicName || this.type || "example";
		var component = this.getComponent();
		setExampleLabel(component.queryById("mainFileSelector"), label + " — values");
		setExampleLabel(component.queryById("secondaryFileSelector"),
			label + " — relevant features");
	};
	/*********************************************************************
	* COMPONENT DECLARATION
	***********************************************************************/
	this.initComponent = function() {
		var me = this;

		this.component = Ext.widget({
			xtype: "container", flex: 1, cls: "omicbox",
			type: me.type, layout: {align: 'stretch',type: 'vbox'},
			items: [
				{
					xtype: "box", flex: 1, cls: "omicboxTitle " + this.class, html:
					'<h4>' +
					' <a class="deleteOmicBox" href="javascript:void(0)" style="margin: 0; float:right;  padding-right: 15px;"><i class="fa fa-trash"></i></a>' +
					this.title +
					'</h4>'
				}, {
					xtype: "container",
					layout: {align: 'stretch',type: 'vbox'},
					padding: 10,
					/* No maxWidth here, nor in the other panel types that repeat this
					   block: the "Selected omics" column is ~700px wide, so the 500px cap
					   this used to carry stopped every row well short of its own box and
					   left a band of dead white down the right of each omic panel. The
					   vbox is align:'stretch', so without the cap each field fills the
					   panel it is in. */
					defaults: {
						labelAlign: "right",
						labelWidth: 150,
						maxLength: 100
					},
					items: [
						{
							xtype: 'combo',
							fieldLabel: 'Omic Name',
							name: this.namePrefix + '_omic_name',
							value: this.omicName,
							hidden: this.omicName !== "",
							itemId: "omicNameField",
							displayField: 'name',
							valueField: 'name',
							emptyText: 'Type or choose the omic type',
							editable: true,
							allowBlank: false,
							queryMode: 'local',
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['name'],
								autoLoad: true,
								proxy: {
									type: 'ajax',
									url: 'resources/data/all_omics.json',
									reader: {
										type: 'json',
										root: 'omics',
										successProperty: 'success'
									}
								}
							})
						}, {
							xtype: "myFilesSelectorButton",
							fieldLabel: 'Data file',
							namePrefix: this.namePrefix,
							itemId: "mainFileSelector",
							helpTip: "Upload the feature quantification file (Gene expression, proteomics quantification,...) or choose it from your data folder."
						}, {
							xtype: 'combo', itemId: "fileTypeSelector",
							fieldLabel: 'File Type', emptyText: 'Type or choose the file type',
							name: this.namePrefix + '_file_type',
							hidden: this.omicName !== "",
							displayField: 'name', valueField: ' name',
							editable: true, allowBlank: false,
							value: (this.fileType !== null) ? this.fileType : null,
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['name', 'type'],
								autoLoad: true,
								proxy: {
									type: 'ajax',
									url: 'resources/data/file_types.json',
									reader: {type: 'json', root: 'types', successProperty: 'success'}
								},
								filterOnLoad:true,
								filters: [{property: 'type', value : 'data'}]
							}),
							helpTip: "Specify the type of data for uploaded file (Gene Expression file, Proteomic quatification,...)."
						}, {
							xtype: "myFilesSelectorButton",
							fieldLabel: 'Relevant features file',
							namePrefix: this.namePrefix + '_relevant',
							itemId: "secondaryFileSelector",
							helpTip: "Upload the list of relevant features (relevant genes, relevant proteins,...)."
						}, {
							xtype: 'combo', itemId: "relevantFileTypeSelector",
							fieldLabel: 'File Type', emptyText: 'Type or choose the file type',
							name: this.namePrefix + '_relevant_file_type',
							hidden: this.omicName !== "",
							displayField: 'name', valueField: 'name',
							editable: true, allowBlank: false,
							value: (this.relevantFileType !== null) ? this.relevantFileType : null,
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['name', 'type'],
								autoLoad: true,
								proxy: {
									type: 'ajax',
									url: 'resources/data/file_types.json',
									reader: {type: 'json', root: 'types', successProperty: 'success'}
								},
								filterOnLoad:true,
								filters: [{property: 'type', value : 'list'}]
							}),
							helpTip: "Specify the type of data for uploaded file (Relevant Genes list, Relevant proteins list,...)."
						}, {
							xtype: 'combo',
							fieldLabel: 'Can be mapped to',
							name: this.namePrefix + '_match_type',
							hidden: this.omicName !== "",
							itemId: "mapToSelector",
							displayField: 'name', valueField: 'value',
							emptyText: 'Choose the file type',
							value: this.mapTo,
							editable: false,
							allowBlank: false,
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['name', 'value'],
								data: [
									['Genes', 'gene'],
									['Metabolites', 'compound']
								]
							}),
							helpTip: "Defines whether the data can be assigned to Genes or to Metabolites, for example  the values of concentration for proteins that can be mapped to the corresponding codifying gene."
						},
						{
							xtype: 'combo',
							fieldLabel: 'Enrichment type',
							name: this.namePrefix + '_enrichment',
							hidden: this.omicName !== "",
							value: this.featureEnrichment.toString(),
							displayField: 'name', valueField: 'value',
							editable: false,
							allowBlank: false,
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['name', 'value'],
								data: [
									['Genes', 'genes'],
									['Features', 'features']
								]
							}),
							helpTip: "Define how the Fisher contingency table must be done: counting genes or features (i.e: microRNA, proteins...)."
						}
					]
				}
			],
			isValid: function() {
				var valid = true;

				if (this.isEmpty) {
					return true;
				}

				if (this.queryById("omicNameField").getValue() === "") {
					valid = false;
					this.queryById("omicNameField").markInvalid("Please, specify a Omic Name.");
				}
				if (this.queryById("mainFileSelector").getValue() === "") {
					valid = false;
					this.queryById("mainFileSelector").markInvalid("Please, provide a Data file.");
				}
				if (this.queryById("fileTypeSelector").getValue() === null) {
					valid = false;
					this.queryById("fileTypeSelector").markInvalid("Please, specify a File type.");
				}
				if (this.queryById("secondaryFileSelector").getValue() !== "" && this.queryById("relevantFileTypeSelector").getValue() === null) {
					valid = false;
					this.queryById("relevantFileTypeSelector").markInvalid("Please, specify a File type.");
				}
				if (this.queryById("mapToSelector").getValue() === null) {
					valid = false;
					this.queryById("mapToSelector").markInvalid("Please, specify a this field.");
				}

				return valid;
			},
			isEmpty: function() {
				return (this.queryById("secondaryFileSelector").getValue() === "" && this.queryById("mainFileSelector").getValue() === "");
			},
			listeners: {
				boxready: function() {
					initializeTooltips(".helpTip");

					$(this.getEl().dom).find("a.deleteOmicBox").click(function() {
						me.removeOmicSubmittingPanel();
					});
				}
			}
		});

		return this.component;
	};
	return this;
}
OmicSubmittingPanel.prototype = new DefaultSubmittingPanel;

function RegionBasedOmicSubmittingPanel(nElem, options) {
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	options = (options || {});

	this.title = "Region-based omic";
	this.namePrefix = "omic" + nElem;
	this.omicName = "";
	this.mapTo = "Gene";
	this.fileType = null;
	this.relevantFileType = null;
	this.featureEnrichment = "genes";

	this.allowToogle = options.allowToogle !== false;
	this.removable = options.removable !== false;

	this.class = "bedbasedFileBox";

	/*IF THE TYPE WAS SPECIFIED (e.g. gene_expression)*/
	if (options.type !== undefined) {
		//TODO CAPITALIZE THE FIRST LETTER
		this.omicName = options.type;
		this.title = options.type;

		this.fileType = options.fileType;
		this.relevantFileType = options.relevantFileType;
		this.type = this.title.replace(" ", "").toLowerCase();
		this.class = this.type + "FileBox";
	}
	/*********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/

	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	/**
	* Display-only example mode. The server resolves the real files from the
	* manifest, so only labels are set here.
	*
	* The names are no longer hardcoded. They used to be literal paths
	* ("example/dnase_unmapped_values.tab"), which was already the second
	* attempt -- before that they were built from `this.type`, and the
	* Regions2Genes tool constructs this panel with no type, so the form
	* displayed "example/undefined_example.tab". Taking them from the chosen
	* scenario means they cannot go stale when the files move again.
	*
	* @param {Object} [scenario] the entry from /example_datasets.
	*/
	this.setExampleMode = function(scenario){
		var component = this.getComponent();
		//component.queryById("toogleMapRegions").setVisible(false);

		component = component.queryById("itemsContainer");

		var omicName = (scenario && scenario.omicNames && scenario.omicNames[0]) ||
			"Region-based omic";

		setExampleLabel(component.queryById("mainFileSelector"),
			omicName + " — region values");
		setExampleLabel(component.queryById("secondaryFileSelector"),
			omicName + " — relevant regions");
		setExampleLabel(component.queryById("tertiaryFileSelector"),
			"genome annotation (GTF)");

		var field = component.queryById("omicNameField");
		field.setValue(omicName);
		field.setDisabled(true);

		var otherFields = ["distanceField", "tssDistanceField", "promoterDistanceField", "geneAreaPercentageField", "regionAreaPercentageField", "gtfTagField", "summarizationMethodField", "reportSelector1","reportSelector2"];
		for(var i in otherFields){
			field = component.queryById(otherFields[i]);
			field.setReadOnly(true);
		}
	};
	this.setContent = function(target, values) {
		var component = this.getComponent().queryById(target);

		if (values.title) {
			component.queryById("omicNameField").setValue(values.title);
		}
		if (values.omicName) {
			component.queryById("omicNameField").setValue(values.omicName);
		}
		if (values.mainFile) {
			component.queryById("mainFileSelector").setValue(values.mainFile);
		}
		if (values.mainFileType) {
			component.queryById("fileTypeSelector").setValue(values.mainFileType);
		}
		if (values.secondaryFile) {
			component.queryById("secondaryFileSelector").setValue(values.secondaryFile);
		}
		if (values.secondaryFileType) {
			component.queryById("relevantFileTypeSelector").setValue(values.secondaryFileType);
		}
		if (values.toogleMapRegions) {
			component.queryById("toogleMapRegions").setVisible(values.toogleMapRegions === true);
		}
		if (values.configVars) {
			component.queryById("configVars").setValue(values.configVars);
		}
		if (values.enrichmentType) {
			component.queryById("enrichmentType").setValue(values.enrichmentType);
		}
		if (values.ignoreMissing) {
			component.queryById("ignoreMissing").setValue(values.ignoreMissing);
		}

		if (!component.isVisible()) {
			this.toogleContent();
		}
		return this;
	};

	/*********************************************************************
	* COMPONENT DECLARATION
	***********************************************************************/
	this.initComponent = function() {
		var me = this;
		this.component = Ext.widget({
			xtype: "container",
			flex: 1,
			type: me.type,
			cls: "omicbox regionBasedOmic",
			layout: {
				align: 'stretch',
				type: 'vbox'
			},
			items: [{
				xtype: "box",
				flex: 1,
				cls: "omicboxTitle " + this.class,
				html: '<h4><a class="deleteOmicBox" href="javascript:void(0)" style="margin: 0; float:right;  padding-right: 15px;">' +
				(me.removable ? ' <i class="fa fa-trash"></i></a>' : "</a>") + this.title +
				'</h4>'
			}, {
				xtype: "box",
				itemId: "toogleMapRegions",
				hidden: !this.allowToogle,
				html: '<div class="checkbox" style=" margin: 10px 50px; font-size: 16px; "><input type="checkbox" id="' + this.namePrefix + '_mapRegions"><label for="' + this.namePrefix + '_mapRegions">My regions are already mapped to Gene IDs, skip this step.</label></div>'
			},
			{
				xtype: "box",
				itemId: "toogleUseAssociations",
				hidden: !this.allowToogle,
				html: '<div class="checkbox" style=" margin: 10px 50px; font-size: 16px; "><input type="checkbox" id="' + this.namePrefix + '_useAssociations"><label for="' + this.namePrefix + '_useAssociations">Provide own associations lists.</label></div>'
			}, {
				xtype: "container",
				itemId: "itemsContainerAlt",
				layout: {
					align: 'stretch',
					type: 'vbox'
				},
				padding: 10,
				hidden: true,
				disabled: true,
				defaults: {
					labelAlign: "right",
					labelWidth: 150,
					maxLength: 100
				},
				items: [{
					xtype: 'combo',
					fieldLabel: 'Omic Name',
					name: this.namePrefix + '_omic_name',
					value: this.omicName,
					itemId: "omicNameField",
					displayField: 'name',
					valueField: 'name',
					emptyText: 'Type or choose the omic type',
					queryMode: 'local',
					hidden: this.omicName !== "",
					editable: true,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name'],
						autoLoad: true,
						proxy: {
							type: 'ajax',
							url: 'resources/data/all_omics.json',
							reader: {
								type: 'json',
								root: 'omics',
								successProperty: 'success'
							}
						}
					})
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Data file',
					namePrefix: this.namePrefix,
					itemId: "mainFileSelector",
					helpTip: "Upload the feature quantification file (Gene expression, proteomics quantification,...) or choose it from your data folder."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_file_type',
					itemId: "fileTypeSelector",
					value: "Bed file (regions mapped to Genes)",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Gene Expression file, Proteomic quatification,...)."
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Relevant features file',
					namePrefix: this.namePrefix + '_relevant',
					itemId: "secondaryFileSelector",
					helpTip: "Upload the list of relevant features (relevant genes, relevant proteins,...)."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_relevant_file_type',
					itemId: "relevantFileTypeSelector",
					value: "Relevant regions list (mapped to Genes)",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Relevant Genes list, Relevant proteins list,...)."
				}, {
					xtype: 'textfield',
					fieldLabel: 'Map to',
					name: this.namePrefix + '_match_type',
					itemId: "mapToSelector",
					value: this.mapTo,
					hidden: true
				},{
					xtype: 'textfield',
					name: this.namePrefix + '_config_args',
					hidden: true,
					itemId: 'configVars',
					maxLength: 1000
				}, {
					xtype: 'combo',
					itemId: 'enrichmentType',
					fieldLabel: 'Enrichment type',
					name: this.namePrefix + '_enrichment',
					hidden: this.omicName !== "",
					value: this.featureEnrichment.toString(),
					displayField: 'name', valueField: 'value',
					editable: false,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name', 'value'],
						data: [
							['Genes', 'genes'],
							['Features', 'features'],
							['Associations', 'associations']
						]
					}),
					helpTip: "Define how the Fisher contingency table must be done: counting genes, features (i.e: microRNA, proteins...) or associations (combination of feature & gene)."
				}]
			}, {
				xtype: "container",
				itemId: "itemsContainerAssociations",
				layout: {
					align: 'stretch',
					type: 'vbox'
				},
				disabled: true,
				defaults: {
					labelAlign: "right",
					labelWidth: 150,
					maxLength: 100
				},
				hidden: true,
				items: [{
					xtype: 'combo',
					fieldLabel: 'Omic Name',
					name: this.namePrefix + '_omic_name',
					value: this.omicName,
					itemId: "omicNameField",
					displayField: 'name',
					valueField: 'name',
					emptyText: 'Type or choose the omic type',
					queryMode: 'local',
					hidden: this.omicName !== "",
					editable: true,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name'],
						autoLoad: true,
						proxy: {
							type: 'ajax',
							url: 'resources/data/all_omics.json',
							reader: {
								type: 'json',
								root: 'omics',
								successProperty: 'success'
							}
						}
					})
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Data file',
					namePrefix: this.namePrefix,
					itemId: "mainFileSelector",
					helpTip: "Upload the feature quantification file (Gene expression, proteomics quantification,...) or choose it from your data folder."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_file_type',
					itemId: "fileTypeSelector",
					value: "Map file (features mapped to Genes)",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Gene Expression file, Proteomic quatification,...)."
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Relevant features file',
					namePrefix: this.namePrefix + '_relevant',
					itemId: "secondaryFileSelector",
					helpTip: "Upload the list of relevant features (relevant genes, relevant proteins,...)."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_relevant_file_type',
					itemId: "relevantFileTypeSelector",
					value: "Relevant regulators list (mapped to Genes)",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Relevant Genes list, Relevant proteins list,...)."
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Associations file',
					namePrefix: this.namePrefix + '_associations',
					itemId: "mainAssociationFileSelector",
					helpTip: "Upload the 2 column association file associating genes with features or choose it from your data folder."
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Relevant associations file',
					namePrefix: this.namePrefix + '_relevant_associations',
					itemId: "secondaryAssociationFileSelector",
					helpTip: "Upload the 2 column list of relevant associations (gene - feature) or choose it from your data folder."
				}, {
					xtype: 'textfield',
					fieldLabel: 'Map to',
					name: this.namePrefix + '_match_type',
					itemId: "mapToSelector",
					value: this.mapTo,
					hidden: true
				},{
					xtype: 'textfield',
					name: this.namePrefix + '_config_args',
					hidden: true,
					itemId: 'configVars',
					maxLength: 1000
				},
				{
					xtype: 'combo',
					itemId: 'enrichmentType',
					fieldLabel: 'Enrichment type',
					name: this.namePrefix + '_enrichment',
					hidden: this.omicName !== "",
					value: this.featureEnrichment.toString(),
					displayField: 'name', valueField: 'value',
					editable: false,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name', 'value'],
						data: [
							['Genes', 'genes'],
							['Features', 'features'],
							['Associations', 'associations']
						]
					}),
					helpTip: "Define how the Fisher contingency table must be done: counting genes, features (i.e: microRNA, proteins...) or the relevant associations (combination of genes & features)."
				}]
			}, {
				xtype: "container",
				itemId: "itemsContainer",
				layout: {
					align: 'stretch',
					type: 'vbox'
				},
				padding: 10,
				defaults: {
					labelAlign: "right",
					labelWidth: 150,
					maxLength: 100
				},
				items: [{
					xtype: 'textfield',
					name: "name_prefix",
					hidden: true,
					itemId: "namePrefix",
					value: this.namePrefix
				}, {
					xtype: 'combo',
					fieldLabel: 'Omic Name',
					name: this.namePrefix + '_omic_name',
					hidden: this.omicName !== "",
					itemId: "omicNameField",
					displayField: 'name',
					valueField: 'name',
					emptyText: 'Type or choose the omic type',
					editable: true,
					queryMode: 'local',
					allowBlank: false,
					value: (this.fileType !== null) ? this.fileType : null,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name'],
						autoLoad: true,
						proxy: {
							type: 'ajax',
							url: 'resources/data/all_omics.json',
							reader: {
								type: 'json',
								root: 'omics',
								successProperty: 'success'
							}
						}
					})
				}, {
					xtype: 'textfield',
					hidden: true,
					fieldLabel: 'Map to',
					name: this.namePrefix + '_match_type',
					itemId: "mapToSelector",
					value: this.mapTo
				},
				/*REGIONS FILE*/
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Regions file <br>(BED + Quantification)',
					namePrefix: this.namePrefix,
					itemId: "mainFileSelector",
					helpTip: "Upload the regions file (BED format + Quantification) or choose it from your data folder."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_file_type',
					hidden: true,
					itemId: "fileTypeSelector",
					value: "Bed file (regions)"
				},
				/*RELEVANT REGIONS FILE*/
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: "Relevant regions file",
					namePrefix: this.namePrefix + '_relevant',
					itemId: "secondaryFileSelector",
					helpTip: "Upload the list of relevant regions (TAB format) or choose it from your data folder."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_relevant_file_type',
					hidden: true,
					itemId: "relevantFileTypeSelector",
					value: "Relevant regions list"
				},
				/*ANNOTATIONS FILE*/
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: "Annotations file (GTF)",
					namePrefix: this.namePrefix + '_annotations',
					itemId: "tertiaryFileSelector",
					extraButtons: [{
						text: 'Use a GTF from Paintomics',
						handler: function() {
							var me = this;
							var _callback = function(selectedItem) {
								if (selectedItem !== null) {
									me.up("myFilesSelectorButton").queryById("visiblePathField").setValue("[inbuilt GTF files]/" + selectedItem[0].get("fileName"));
									me.up("myFilesSelectorButton").queryById("originField").setValue("inbuilt_gtf");
								}
							};
							Ext.widget("GTFSelectorDialog").showDialog(_callback);
						}
					}],
					helpTip: "Upload the Annotations file (GTF format), choose it from your data folder or browse the GFT files included in Paintomics."
				}, {
					xtype: 'textfield',
					hidden: true,
					fieldLabel: 'File Type',
					name: this.namePrefix + '_annotations_file_type',
					itemId: "referenceFileTypeSelector",
					value: "GTF file"
				},
				/*
				* OTHER FIELDS
				*/
				//report
				{
					xtype: 'textfield',
					hidden: true,
					name: this.namePrefix + '_report',
					fieldLabel: 'Report',
					value: "gene"
				},
				// allow missing
				{
					xtype: 'checkbox',
					itemId: "ignoreMissing",
					name: this.namePrefix + '_ignoremissing',
					fieldLabel: 'Ignore missing entries',
					checked: true,
					allowBlank: false,
					helpTip: "Allow those BED regions with chromosome names not present in the GTF file to be ignored instead of throwing an error."					
				},
				//distance
				{
					xtype: 'numberfield',
					itemId: "distanceField",
					name: this.namePrefix + '_distance',
					fieldLabel: 'Distance (kb)',
					value: 10,
					minValue: 0,
					allowDecimals: false,
					allowBlank: false,
					helpTip: "Maximum distance in kb to report associations. Default: 10 (10kb)"
				},
				//tss
				{
					xtype: 'numberfield',
					itemId: "tssDistanceField",
					name: this.namePrefix + '_tss',
					fieldLabel: 'TSS region distance (bps)',
					value: 200,
					minValue: 0,
					allowDecimals: false,
					allowBlank: false,
					helpTip: "TSS region distance. Default: 200 bps"
				},
				//promoter
				{
					xtype: 'numberfield',
					itemId: "promoterDistanceField",
					name: this.namePrefix + '_promoter',
					fieldLabel: 'Promoter region distance (bps)',
					value: 1300,
					minValue: 0,
					allowDecimals: false,
					allowBlank: false,
					helpTip: "Promoter region distance. Default: 1300 bps"
				},
				//geneAreaPercentage
				{
					xtype: 'numberfield',
					itemId: "geneAreaPercentageField",
					name: this.namePrefix + '_geneAreaPercentage',
					fieldLabel: 'Overlapped gene area (%)',
					// 90, not 50: the helpTip below, Bed2GeneJob's own default
					// (Bed2GeneJob.py:50) and the servlet's fallback
					// (Bed2GenesServlet.py:147) all say 90. The field posts on every
					// request, so the 50 that sat here was silently overriding the
					// documented default for every region-based job.
					value: 90,
					minValue: 0,
					maxValue: 100,
					allowDecimals: false,
					allowBlank: false,
					helpTip: "Percentage of the area of the gene overlapped to be considered to discriminate at transcript and gene level. Default: 90 (90%)"
				},
				//regionAreaPercentage
				{
					xtype: 'numberfield',
					itemId: "regionAreaPercentageField",
					name: this.namePrefix + '_regionAreaPercentage',
					fieldLabel: 'Overlapped region area (%)',
					value: 50,
					minValue: 0,
					maxValue: 100,
					allowDecimals: false,
					allowBlank: false,
					helpTip: "Percentage of the region overlapped by the gene to be considered to discriminate at transcript and gene level. Default: 50 (50%)"
				},
				//rules //TODO
				//{xtype: 'textfield', hidden: true, fieldLabel: 'rules', name: this.namePrefix + '_report', itemId: "reportSelector", value: "gene"},
				//geneIDtag
				{
					xtype: 'textfield',
					itemId: "gtfTagField",
					name: this.namePrefix + '_geneIDtag',
					fieldLabel: 'GTF Tag for gene ID/name ',
					value: "gene_id",
					allowBlank: false,
					helpTip: "GTF tag used to get gene ids/names. Default: gene_id"
				},
				//summarization_method
				{
					xtype: 'combo',
					itemId: "summarizationMethodField",
					name: this.namePrefix + '_summarization_method',
					fieldLabel: 'Summarization method',
					editable: false,
					allowBlank: false,
					value: "mean",
					displayField: 'label',
					valueField: 'value',
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['label', 'value'],
						data: [
							["None", "none"],
							["Mean", "mean"],
							["Maximum", "max"]
						]
					}),
					helpTip: "Choose the strategy used to resolve regions mapping to the same gen region. Default: 'Mean'"
				},{
					xtype: 'combo',
					fieldLabel: 'Enrichment type',
					name: this.namePrefix + '_enrichment_pre',
					hidden: this.omicName !== "",
					value: this.featureEnrichment.toString(),
					displayField: 'name', valueField: 'value',
					editable: false,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name', 'value'],
						data: [
							['Genes', 'genes'],
							['Features', 'features'],
							['Associations', 'associations']
						]
					}),
					helpTip: "Define how the Fisher contingency table must be done: counting genes, features (i.e: microRNA, proteins...) or associations (combination of genes & features)."
				},{
					xtype: 'fieldcontainer',
					fieldLabel: 'Report',
					defaultType: 'radiofield',
					items: [{
						boxLabel: 'All regions',
						itemId: "reportSelector1",
						name: this.namePrefix + '_report',
						submitValue: false,
						checked: true,
						listeners: {
							change: function(radio, newValue, oldValue) {
								radio.up().queryById("reportOptionsContainer").setVisible(!newValue);
								var elems = radio.up().queryById("reportOptionsContainer").query("checkboxfield");
								for (var i in elems) {
									elems[i].setDisabled(newValue);
								}
								elems = radio.up().queryById("reportAllRegionsOption");
								elems.setDisabled(!newValue);
								elems.setValue(newValue);
							}
						}
					}, {
						boxLabel: 'Let me choose',
						itemId: "reportSelector2",
						name: this.namePrefix + '_report',
						submitValue: false,
						helpTip: "Indicates which regions will be selected from rgmatch output. E.g. Option 'First exon' will filter out all regions that do not map into the first exon of the corresponding gene."
					}, {
						xtype: 'container',
						defaultType: 'checkboxfield',
						hidden: true,
						itemId: 'reportOptionsContainer',
						items: [{
							xtype: 'label',
							text: 'Regions mapping at...'
						}, {
							boxLabel: 'All regions',
							name: this.namePrefix + '_reportRegions',
							inputValue: 'all',
							itemId: 'reportAllRegionsOption',
							checked: true,
							hidden: true
						}, {
							xtype: 'container',
							layout: 'hbox',
							defaultType: 'checkboxfield',
							defaults: {
								hideLabel: false,
								labelAlign: 'top',
								boxLabel: '',
								labelSeparator: "",
								style: 'text-align: center'
							},
							items: [{
								fieldLabel: 'Upstream',
								name: this.namePrefix + '_reportRegions',
								inputValue: 'UPSTREAM',
								labelStyle: 'padding: 2px 3px; font-size:9px; background-color: #E3CEB0;'
							}, {
								fieldLabel: 'Promoter',
								name: this.namePrefix + '_reportRegions',
								inputValue: 'PROMOTER',
								labelStyle: 'padding: 2px 3px; font-size:9px; background-color: #FFF2C0;'
							}, {
								fieldLabel: 'TSS',
								name: this.namePrefix + '_reportRegions',
								inputValue: 'TSS',
								labelAlign: 'top',
								labelStyle: 'padding: 2px 3px; font-size:9px; background-color: #FFF6D3;'
							}, {
								fieldLabel: '1st Exon',
								name: this.namePrefix + '_reportRegions',
								inputValue: '1st_EXON',
								labelStyle: 'padding: 2px 3px; font-size:9px; background-color: #FFC4AD;'
							}, {
								fieldLabel: 'Introns',
								name: this.namePrefix + '_reportRegions',
								inputValue: 'INTRON',
								labelStyle: 'padding: 2px 3px; font-size:9px; background-color: #D0DFF1;'
							}, {
								fieldLabel: 'Gene body',
								name: this.namePrefix + '_reportRegions',
								inputValue: 'GENE_BODY',
								labelStyle: 'padding: 2px 3px; font-size:9px; background-color: #FFE0D3;'
							}, {
								xtype: 'label',
								text: 'Intr.',
								style: 'padding: 5px 3px; font-size:9px; margin-top:4px; background-color: #D0DFF1;'
							}, {
								xtype: 'label',
								text: 'G.B.',
								style: 'padding: 5px 3px; font-size:9px; margin-top:4px;  background-color: #FFE0D3;'
							}, {
								fieldLabel: 'Downstream',
								name: this.namePrefix + '_reportRegions',
								inputValue: 'DOWNSTREAM',
								labelStyle: 'padding: 2px 3px; font-size:9px; background-color: #B2C9E3;'
							}]
						}]
					}]
				},
			]
		}],
		setContent: function(target, values) {
			me.setContent(target, values);
		},
		isValid: function() {
			var valid = true;
			var component = this.queryById("itemsContainerAlt");
			if (!component.isVisible()) {
				component = this.queryById("itemsContainerAssociations");

				if (!component.isVisible()) {
					component = this.queryById("itemsContainer");
				}
			}
			var items = component.query("field");
			for (var i in items) {
				valid = valid && (this.items[i] || items[i].validate());
			}

			if (component.queryById("mainFileSelector").getValue() === "") {
				valid = false;
				component.queryById("mainFileSelector").markInvalid("Please, provide a Data file.");
			}
			if (component.queryById("tertiaryFileSelector") && component.queryById("tertiaryFileSelector").getValue() === "") {
				valid = false;
				component.queryById("tertiaryFileSelector").markInvalid("Please, provide a GTF file.");
			}

			if (this.queryById("reportOptionsContainer").query("checkboxfield[checked=true]") < 1) {
				valid = false;
				this.queryById("reportOptionsContainer").query("checkboxfield").forEach(function(elem) {
					elem.markInvalid("Please, check at least one gene region.");
				});
			}

			return valid;
		},
		isEmpty: function() {
			var component = this.queryById("itemsContainerAlt");
			if (!component.isVisible()) {
				component = this.queryById("itemsContainerAssociations");

				if (!component.isVisible()) {
					component = this.queryById("itemsContainer");
				}
			}
			var empty = true;
			if (component.queryById("mainFileSelector").getValue() !== "") {
				empty = false;
			}
			if (component.queryById("tertiaryFileSelector") && component.queryById("tertiaryFileSelector").getValue() !== "") {
				empty = false;
			}

			return empty;
		},
		listeners: {
			boxready: function() {
				initializeTooltips(".helpTip");

				$("#" + me.namePrefix + "_mapRegions").change(function() {
					me.getComponent().queryById("toogleUseAssociations").setVisible(! $(this).is(':checked'));
					me.toogleContent();
				});

				$("#" + me.namePrefix + "_useAssociations").change(function() {
					me.getComponent().queryById("toogleMapRegions").setVisible(! $(this).is(':checked'));
					me.toogleContent("itemsContainerAssociations");
				});

				$(this.getEl().dom).find("a.deleteOmicBox").click(function() {
					me.removeOmicSubmittingPanel();
				});
			}
		}
	});

	return this.component;
};

return this;
}
RegionBasedOmicSubmittingPanel.prototype = new DefaultSubmittingPanel;

function MiRNAOmicSubmittingPanel(nElem, options) {
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	options = (options || {});

	this.title = (options.regulatoryMethod === "pairwise")
		? "Regulatory Omic — Pairwise"
		: "Regulatory Omic";
	this.namePrefix = "omic" + nElem;
	this.omicName = "";
	this.mapTo = "Gene";
	this.fileType = null;
	this.relevantFileType = null;
	this.featureEnrichment = "genes";

	this.allowToogle = options.allowToogle !== false;
	this.removable = options.removable !== false;

	this.class = "miRNAbasedFileBox";

	/*IF THE TYPE WAS SPECIFIED (e.g. gene_expression)*/
	if (options.type !== undefined) {
		//TODO CAPITALIZE THE FIRST LETTER
		this.omicName = options.type;
		this.title = options.type;

		this.fileType = options.fileType;
		this.relevantFileType = options.relevantFileType;
		this.type = this.title.replace(" ", "").toLowerCase();
		this.class = this.type + "FileBox";
	}
	/*********************************************************************
	* GETTERS AND SETTERS
	***********************************************************************/

	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	/**
	* Display-only example mode; the server resolves the files from the
	* manifest. `mirna_unmapped.tab` was named here for years while the file
	* that actually ships is `mirna_unmapped_values.tab` -- a label nobody could
	* act on, and exactly the drift that taking the names from the scenario
	* prevents.
	*
	* @param {Object} [scenario] the entry from /example_datasets.
	*/
	this.setExampleMode = function(scenario){
		var component = this.getComponent();
		//component.queryById("toogleMapRegions").setVisible(false);
		component = component.queryById("itemsContainer");

		var omicNames = (scenario && scenario.omicNames) || ["miRNA"];
		var regulator = omicNames[0];

		setExampleLabel(component.queryById("mainFileSelector"),
			regulator + " — values");
		setExampleLabel(component.queryById("secondaryFileSelector"),
			regulator + " — relevant features");
		setExampleLabel(component.queryById("mirnaTargetsFileSelector"),
			regulator + " — target predictions");
		setExampleLabel(component.queryById("rnaseqauxFileSelector"),
			"target gene expression");

		var field = component.queryById("omicNameField");
		field.setValue(regulator);
		field.setDisabled(true);

		var otherFields = ["summarizationMethodField"];
		for(var i in otherFields){
			field = component.queryById(otherFields[i]);

			if (field != null) {
			    field.setReadOnly(true);
			}
		}

		// Turn on the correlation option, which is what this example actually
		// runs: MiRNA2GenesServlet's example branch supplies a transcriptomics
		// file and correlation parameters (kendall / negative_correlation) and
		// no relevant-associations file. setExampleMode already fills in
		// rnaseqauxFileSelector for that path but left the checkbox unticked,
		// so isValid() took the other branch and demanded the associations file
		// -- a field the form itself labels "(optional)". The example could
		// therefore never be submitted: it failed with "Invalid form. Please
		// check form errors." every time.
		//
		// The tick has to wait for boxready. The checkbox is raw HTML inside a
		// box component, and setExampleMode runs before the panel is added to
		// the form, so it is not in the document yet -- every other field here
		// is reached through queryById, which works on the unrendered component
		// tree. Registering the listener now also means it runs after the one
		// declared in the component config, so the change handler that enables
		// the correlation options is already bound when the event is triggered.
		// `this`, not `me`: var me = this is scoped to initComponent.
		var panel = this;
		var enableCorrelationMode = function() {
			var $corr = $("#" + panel.namePrefix + "_corrOptions");
			if (!$corr.length) return;
			$corr.prop("checked", true).trigger("change");
			$corr.prop("disabled", true);
		};

		var panelComponent = this.getComponent();
		if (panelComponent.rendered) {
			enableCorrelationMode();
		} else {
			panelComponent.on("boxready", enableCorrelationMode, null, {single: true});
		}
	};
	this.setContent = function(target, values) {
		var component = this.getComponent().queryById(target);

		if (values.title) {
			component.queryById("omicNameField").setValue(values.title);
		}
		if (values.omicName) {
			component.queryById("omicNameField").setValue(values.omicName);
		}
		if (values.mainFile) {
			component.queryById("mainFileSelector").setValue(values.mainFile);
		}
		if (values.mainFileType) {
			component.queryById("fileTypeSelector").setValue(values.mainFileType);
		}
		if (values.secondaryFile) {
			component.queryById("secondaryFileSelector").setValue(values.secondaryFile);
		}
		if (values.secondaryFileType) {
			component.queryById("relevantFileTypeSelector").setValue(values.secondaryFileType);
		}
		if (values.thirdFile) {
			component.queryById("thirdFileSelector").setValue(values.thirdFile);
		}
		if (values.thirdFileType) {
			component.queryById("associationsFileTypeSelector").setValue(values.thirdFileType);
		}
		if (values.fourthFile) {
			component.queryById("fourthFileSelector").setValue(values.fourthFile);
		}
		if (values.fourthFileType) {
			component.queryById("associationsRelevantFileTypeSelector").setValue(values.fourthFileType);
		}
		if (values.toogleMapRegions) {
			component.queryById("toogleMapRegions").setVisible(values.toogleMapRegions === true);
		}
		if (values.configVars) {
			component.queryById("configVars").setValue(values.configVars);
		}
		if (values.enrichmentType) {
			component.queryById("enrichmentType").setValue(values.enrichmentType);
		}

		if (!component.isVisible()) {
			this.toogleContent();
		}
		return this;
	};

	/*********************************************************************
	* COMPONENT DECLARATION
	***********************************************************************/
	this.initComponent = function() {
		var me = this;
		this.component = Ext.widget({
			xtype: "container",
			flex: 1,
			type: me.type,
			cls: "omicbox miRNABasedOmic",
			layout: {
				align: 'stretch',
				type: 'vbox'
			},
			items: [{
				xtype: "box",
				flex: 1,
				cls: "omicboxTitle " + this.class,
				html: '<h4><a class="deleteOmicBox" href="javascript:void(0)" style="margin: 0; float:right;  padding-right: 15px;">' +
				(me.removable ? ' <i class="fa fa-trash"></i></a>' : "</a>") + this.title +
				'</h4>'
			},
			{
				xtype: "box",
				itemId: "toogleMapRegions",
				hidden: !this.allowToogle,
				html: '<div class="checkbox" style=" margin: 10px 50px; font-size: 16px; "><input type="checkbox" id="' + this.namePrefix + '_mapRegions"><label for="' + this.namePrefix + '_mapRegions">My features are already mapped to Gene IDs, skip this step.</label></div>'
			},
			// {
			// 	xtype: "box",
			// 	itemId: "toogleUseAssociations",
			// 	hidden: !this.allowToogle,
			// 	html: '<div class="checkbox" style=" margin: 10px 50px; font-size: 16px; "><input type="checkbox" id="' + this.namePrefix + '_useAssociations"><label for="' + this.namePrefix + '_useAssociations">Provide own associations lists.</label></div>'
			// },
			{
				xtype: "container",
				itemId: "itemsContainerAlt",
				layout: {
					align: 'stretch',
					type: 'vbox'
				},
				disabled: true,
				defaults: {
					labelAlign: "right",
					labelWidth: 150,
					maxLength: 100
				},
				hidden: true,
				items: [{
					xtype: 'combo',
					fieldLabel: 'Omic Name',
					name: this.namePrefix + '_omic_name',
					value: this.omicName,
					itemId: "omicNameField",
					displayField: 'name',
					valueField: 'name',
					emptyText: 'Type or choose the omic type',
					queryMode: 'local',
					hidden: this.omicName !== "",
					editable: true,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name'],
						autoLoad: true,
						proxy: {
							type: 'ajax',
							url: 'resources/data/all_omics.json',
							reader: {
								type: 'json',
								root: 'omics',
								successProperty: 'success'
							}
						}
					})
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Data file',
					namePrefix: this.namePrefix,
					itemId: "mainFileSelector",
					helpTip: "Upload the feature quantification file (Gene expression, proteomics quantification,...) or choose it from your data folder."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_file_type',
					itemId: "fileTypeSelector",
					value: "Map file (features mapped to Genes)",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Gene Expression file, Proteomic quatification,...)."
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Relevant features file',
					namePrefix: this.namePrefix + '_relevant',
					itemId: "secondaryFileSelector",
					helpTip: "Upload the list of relevant features (relevant genes, relevant proteins,...)."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_relevant_file_type',
					itemId: "relevantFileTypeSelector",
					value: "Relevant regulators list (mapped to Genes)",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Relevant Genes list, Relevant proteins list,...)."
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Regulator associations file',
					namePrefix: this.namePrefix + '_associations',
					itemId: "thirdFileSelector",
					helpTip: "Upload the association list."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_associations_file_type',
					itemId: "associationsFileTypeSelector",
					value: "Regulator associations",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Relevant Genes list, Relevant proteins list,...)."
				}, {
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Regulator relevant associations file',
					namePrefix: this.namePrefix + '_relevant_associations',
					itemId: "fourthFileSelector",
					helpTip: "Upload the relevant association list."
				}, {
					xtype: "textfield",
					fieldLabel: 'File Type',
					name: this.namePrefix + '_associations_relevant_file_type',
					itemId: "associationsRelevantFileTypeSelector",
					value: "Regulator relevant associations",
					hidden: true,
					helpTip: "Specify the type of data for uploaded file (Relevant Genes list, Relevant proteins list,...)."
				}, {
					xtype: 'textfield',
					fieldLabel: 'Map to',
					name: this.namePrefix + '_match_type',
					itemId: "mapToSelector",
					value: this.mapTo,
					hidden: true
				},{
					xtype: 'textfield',
					name: this.namePrefix + '_config_args',
					hidden: true,
					itemId: 'configVars',
					maxLength: 1000
				},
				{
					xtype: 'combo',
					itemId: 'enrichmentType',
					fieldLabel: 'Enrichment type',
					name: this.namePrefix + '_enrichment',
					hidden: this.omicName !== "",
					value: this.featureEnrichment.toString(),
					displayField: 'name', valueField: 'value',
					editable: false,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name', 'value'],
						data: [
							['Genes', 'genes'],
							['Features', 'features'],
							['Associations', 'associations']
						]
					}),
					helpTip: "Define how the Fisher contingency table must be done: counting genes, features (i.e: microRNA, proteins...) or associations (combination of genes & features)."
				}]
			}, {
				xtype: "container",
				itemId: "itemsContainer",
				layout: {
					align: 'stretch',
					type: 'vbox'
				},
				padding: 10,
				defaults: {
					labelAlign: "right",
					labelWidth: 150,
					maxLength: 100
				},
				items: [{
					xtype: 'textfield',
					name: "name_prefix",
					hidden: true,
					itemId: "namePrefix",
					value: this.namePrefix
				}, {
					xtype: 'combo',
					fieldLabel: 'Omic Name',
					name: this.namePrefix + '_omic_name',
					hidden: this.omicName !== "",
					itemId: "omicNameField",
					displayField: 'name',
					valueField: 'name',
					emptyText: 'Type or choose the omic type',
					editable: true,
					queryMode: 'local',
					allowBlank: false,
					value: (this.fileType !== null) ? this.fileType : null,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name'],
						autoLoad: true,
						proxy: {
							type: 'ajax',
							url: 'resources/data/all_omics.json',
							reader: {
								type: 'json',
								root: 'omics',
								successProperty: 'success'
							}
						}
					})
				}, {
					xtype: 'textfield',
					hidden: true,
					fieldLabel: 'Map to',
					name: this.namePrefix + '_match_type',
					itemId: "mapToSelector",
					value: this.mapTo
				},
				/*miRNA FILE*/
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Regulators expression file <br>(ie: miRNA expression)',
					namePrefix: this.namePrefix,
					itemId: "mainFileSelector",
					helpTip: "Upload the quantification file (i.e. miRNA Quantification) or choose it from your data folder. See above the accepted format for the file."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_file_type',
					hidden: true,
					itemId: "fileTypeSelector",
					value: "Gene Expression file"
				},
				/*RELEVANT miRNA FILE*/
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: "Relevant regulators file<br> (optional)",
					namePrefix: this.namePrefix + '_relevant',
					itemId: "secondaryFileSelector",
					helpTip: "Upload the list of relevant (differentially expressed) features (TAB format) or choose it from your data folder. See above the accepted format for the file."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_relevant_file_type',
					hidden: true,
					itemId: "relevantFileTypeSelector",
					value: "Relevant gene list"
				},
				{
					xtype: 'combo',
					fieldLabel: 'Enrichment type',
					name: this.namePrefix + '_enrichment_pre',
					hidden: this.omicName !== "",
					value: this.featureEnrichment.toString(),
					displayField: 'name', valueField: 'value',
					editable: false,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name', 'value'],
						data: [
							['Genes', 'genes'],
							['Features', 'features'],
							['Associations', 'associations']
						]
					}),
					helpTip: "Define how the Fisher contingency table must be done: counting genes, features (i.e: microRNA, proteins...) or associations (combination of genes & features)."
				},
				/*TARGETS FILE*/
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: "Associations file",
					namePrefix: this.namePrefix + '_associations',
					itemId: "mirnaTargetsFileSelector",
					helpTip: "Upload the reference file that relates each feature (i.e. miRNA) with its potential targets. This information is usually extracted from popular databases such as miRbase for miRNAs. See above the accepted format for the file."
				}, {
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: this.namePrefix + '_associations_file_type',
					hidden: true,
					itemId: "mirnaTargetsFileTypeSelector",
					value: "Associations file"
				}, /*{
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Associations file',
					namePrefix: this.namePrefix + '_associations',
					itemId: "mainAssociationFileSelector",
					helpTip: "Upload the 2 column association file associating genes with features or choose it from your data folder."
				}*/,
				/*{
					xtype: "box",
					itemId: "toogleCorrOptions",
					hidden: !this.allowToogle,
					html: '<div class="checkbox" style=" margin: 10px 50px; font-size: 16px; "><input type="checkbox" id="' + this.namePrefix + '_corrOptions"><label for="' + this.namePrefix + '_corrOptions">Additional options using correlation.</label></div>'
				},*/
				/* CORRELATION OPTIONS */
				{
					xtype: 'box',
					html: '<hr><p>You can provide a relevant associations file or let the program to automatically retrieve them based on correlation with a gene expression dataset.</p>'
				},
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Relevant associations file<br>(optional)',
					namePrefix: this.namePrefix + '_relevant_associations',
					itemId: "secondaryAssociationFileSelector",
					helpTip: "Upload the 2 column list of relevant associations (gene - feature) or choose it from your data folder."
				},
				{
					xtype: "box",
					itemId: "toogleCorrOptions",
					hidden: !this.allowToogle,
					html: '<div class="checkbox" style=" margin: 10px 50px; font-size: 14px; "><input type="checkbox" id="' + this.namePrefix + '_corrOptions"><label for="' + this.namePrefix + '_corrOptions">Automatically select relevant associations using correlation.</label></div>'		
				},
				/* CORRELATION OPTIONS */
				{
					xtype: "container",
					itemId: "itemsContainerCorrOptions",
					layout: {
						align: 'stretch',
						type: 'vbox'
					},
					disabled: true,
					defaults: {
						labelAlign: "right",
						labelWidth: 150,
						maxLength: 100
					},
					items: [
						{
							xtype: 'textfield',
							fieldLabel: 'Omic Name',
							name: this.namePrefix + '_rnaseqaux_omic_name',
							hidden: true,
							itemId: "rnaseqauxOmicNameField",
							value: "Gene Expression"
						},
						{
							xtype: "myFilesSelectorButton",
							fieldLabel: "Gene expression dataset"/*<br> (optional)"*/,
							namePrefix: this.namePrefix + '_rnaseqaux',
							extraButtons: [{
								text: 'Use a file from other omic',
								handler: function() {
									var me = this;
									var _callback = function(selectedItem) {
										if (selectedItem !== null) {
											me.up("myFilesSelectorButton").queryById("visiblePathField").setValue(selectedItem[0].get("omic") + ": " + selectedItem[0].get("file"));
											me.up("myFilesSelectorButton").queryById("originField").setValue(selectedItem[0].get("name"));
										}
									};
									Ext.widget("OmicInputSelectorDialog").showDialog(_callback);
								}
							}],
							itemId: "rnaseqauxFileSelector",
							helpTip: "Upload the quantification file for the gene expression. This file is used to calculate the correlation of the expression of the genes and their associated features. Using this correlation we can filter and order the features that will be assigned to each gene. See above the accepted format for the file."
						}, {
							xtype: 'textfield',
							fieldLabel: 'File Type',
							name: this.namePrefix + '_rnaseqaux_file_type',
							hidden: true,
							itemId: "rnaseqauxFileTypeSelector",
							value: "Gene Expression file"
						},
						{
							xtype: 'textfield',
							hidden: true,
							fieldLabel: 'Map to',
							name: this.namePrefix + '_rnaseqaux_match_type',
							itemId: "rnaseqauxFileMapToSelector",
							value: 'gene'
						},
						/*
						* OTHER FIELDS
						*/
						//report
						{
							xtype: 'combo',
							itemId: "reportMethodField",
							name: this.namePrefix + '_report',
							fieldLabel: 'Report',
							editable: false,
							allowBlank: false,
							value: "all",
							displayField: 'label',
							valueField: 'value',
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['label', 'value'],
								data: [
									["All features", "all"],
									["Only relevant features (e.g. DE)", "DE"]
								]
							}),
							helpTip: "Choose between consider all features in the quantification file or just those features that are differentially expressed. Default: 'All features'"
						},
						{
							xtype: 'combo',
							itemId: "scoreMethodField",
							name: this.namePrefix + '_score_method',
							fieldLabel: 'Score method',
							editable: false,
							allowBlank: false,
							value: "kendall",
							displayField: 'label',
							valueField: 'value',
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['label', 'value'],
								data: [
									// ["Fold Change of miRNA expression", "fc"],
									["Correlation with gene expression (Spearman)", "spearman"],
									["Correlation with gene expression (Kendall)", "kendall"],
									["Correlation with gene expression (Pearson)", "pearson"]
								]
							}),
							helpTip:
							"As en example in miRNA, usually a single miRNA has multiple potential target genes, but not all targets are being " +
							"regulated by a certain miRNA at certain moment. Consequently, we need to discriminate the real targets for a miRNA."+
							"If Gene expression (GE) data is available, then we calculate the correlation between each miRNA " +
							"and each target gene and filter out all those miRNAs that has a lower correlation value than a given threadhold." +
							"If no GE is available then we filter based on the fold-change for the expression of the miRNAs." +
							"Default: 'Kendall correlation' if GE is available. 'Fold Change' in other case."
						},
						{
							xtype: 'combo',
							itemId: "selectionMethodField",
							name: this.namePrefix + '_selection_method',
							fieldLabel: 'Selection method',
							editable: false,
							allowBlank: false,
							value: "negative_correlation",
							displayField: 'label',
							valueField: 'value',
							store: Ext.create('Ext.data.ArrayStore', {
								fields: ['label', 'value'],
								data: [
									["by max. fold-change of feature expression", "fc"],
									["by absolute correlation with gene expression", "abs_correlation"],
									["by positive correlation with gene expression", "positive_correlation"],
									["by negative correlation with gene expression", "negative_correlation"]
								]
							}),
							//TODO: THIS HELP TOOL IS NOT DISPLAYED, WHY??
							helpTip:
							"Determines how we select the potential features that are regulating a certain gene. " +
							"For instance, usually miRNA act as inhibitors of gene expression so we should expect an opposite behavior " +
							"to the regulated gene. A negative correlation will fit better to this expected profile. " +
							"Default: If gene expression (GE) if avilable, select and order by 'negative correlation'. 'Max fold-change' in other case.",
							listeners:{
								change: function(elem, newValue, oldValue){
									elem = elem.nextSibling("numberfield");
									if(newValue === "negative_correlation"){
										elem.setValue(Math.abs(elem.value) * -1);
									}else{
										elem.setValue(Math.abs(elem.value));
									}
								}
							}
						},
						{
							xtype: 'numberfield',
							itemId: "cutoffField",
							name: this.namePrefix + '_cutoff',
							fieldLabel: 'Filter cutoff',
							value: -0.5,
							minValue: -1,
							maxValue: 1,
							step: 0.1,
							allowDecimals: true,
							allowBlank: false,
							// Deliberately not "features below the cutoff are removed".
							// MiRNA2GeneJob inverts both the cutoff and the score when the
							// selection method is negative correlation (lines 385-386 and
							// 429), so at the -0.5 default an association is kept when its
							// correlation is *more negative* than -0.5. Stating a numeric
							// direction here gets it backwards for the default method; the
							// direction belongs to the method, so that is what is named.
							helpTip: "Threshold for the correlation or fold change, applied in the direction of the selection method above. At the default -0.5 with negative correlation, an association is kept when its correlation is more negative than -0.5."
						}
					]
				}
		]
		}],
		setContent: function(target, values) {
			me.setContent(target, values);
		},
		isValid: function() {
			var valid = true;
			var component = this.queryById("itemsContainerAlt");
			if (!component.isVisible()) {
				component = this.queryById("itemsContainer");
			}
			var items = component.query("field");
			for (var i in items) {
				valid = valid && (this.items[i] || items[i].validate());
			}

			if (component.queryById("mainFileSelector").getValue() === "") {
				valid = false;
				component.queryById("mainFileSelector").markInvalid("Please, provide a data file.");
			}
			if (component.queryById("mirnaTargetsFileSelector") && component.queryById("mirnaTargetsFileSelector").getValue() === "") {
				valid = false;
				component.queryById("mirnaTargetsFileSelector").markInvalid("Please, provide a features targets reference file.");
			}

			var corrEnabled = $("#" + me.namePrefix + "_corrOptions").is(':checked');

			if (corrEnabled && component.queryById("rnaseqauxFileSelector") && component.queryById("rnaseqauxFileSelector").getValue() === "") {
				valid = false;
				component.queryById("rnaseqauxFileSelector").markInvalid("Please, provide a transcriptomics file.");
			} else if(! corrEnabled && component.queryById("secondaryAssociationFileSelector") && component.queryById("secondaryAssociationFileSelector").getValue() === "") {
				valid = false;
				component.queryById("secondaryAssociationFileSelector").markInvalid("Please, provide a relevant associations file or enable the automatic mode instead.");
			}
			return valid;
		},
		isEmpty: function() {
			var component = this.queryById("itemsContainerAlt");
			if (!component.isVisible()) {
				component = this.queryById("itemsContainer");
			}
			var empty = true;
			if (component.queryById("mainFileSelector").getValue() !== "") {
				empty = false;
			}
			if (component.queryById("mirnaTargetsFileSelector") && component.queryById("mirnaTargetsFileSelector").getValue() !== "") {
				empty = false;
			}

			return empty;
		},
		listeners: {
			boxready: function() {
				initializeTooltips(".helpTip");

				$("#" + me.namePrefix + "_mapRegions").change(function() {
					//$("#" + me.namePrefix + "_useAssociations").prop('disabled', $(this).is(':checked'));
					// me.getComponent().queryById("toogleUseAssociations").setVisible(! $(this).is(':checked'));
					me.toogleContent();
				});

				// $("#" + me.namePrefix + "_useAssociations").change(function() {
				// 	// $("#" + me.namePrefix + "_mapRegions").prop('disabled', $(this).is(':checked'));
				// 	me.getComponent().queryById("toogleMapRegions").setVisible(! $(this).is(':checked'));
				// 	me.toogleContent("itemsContainerAssociations");
				// });

				$("#" + me.namePrefix + "_corrOptions").change(function() {
					// $("#" + me.namePrefix + "_mapRegions").prop('disabled', $(this).is(':checked'));
					me.getComponent().queryById("secondaryAssociationFileSelector").down('container').setDisabled($(this).is(':checked'));
					me.getComponent().queryById("itemsContainerCorrOptions").setDisabled(! $(this).is(':checked'));
				});

				$(this.getEl().dom).find("a.deleteOmicBox").click(function() {
					me.removeOmicSubmittingPanel();
				});
			}
		}
	});

	return this.component;
};

return this;
}
MiRNAOmicSubmittingPanel.prototype = new DefaultSubmittingPanel;

function MORESubmittingPanel(nElem, options) {
	/*********************************************************************
	* ATTRIBUTES
	***********************************************************************/
	options = (options || {});
	this.title = "Regulatory Omic — MORE";
	this.namePrefix = "omic" + nElem;
	this.omicName = "MORE Regulatory Omic";
	this.mapTo = "Gene";
	this.type = "moreanalysis";
	this.class = "moreBasedOmic";
	this.allowToogle = false;
	this.removable = options.removable !== false;

	/***********************************************************************
	* OTHER FUNCTIONS
	***********************************************************************/
	this.setContent = function(target, values) {
		var component = this.getComponent().queryById(target);
		if (values.mainFile !== undefined) {
			component.queryById("mainFileFieldAlt").setValue(values.mainFile);
		}
		if (values.secondaryFile !== undefined) {
			component.queryById("secondaryFileFieldAlt").setValue(values.secondaryFile);
		}
		if (values.thirdFile !== undefined) {
			component.queryById("thirdFileFieldAlt").setValue(values.thirdFile);
		}
		if (values.fourthFile !== undefined && values.fourthFile !== null) {
			component.queryById("fourthFileFieldAlt").setValue(values.fourthFile);
		}
		if (values.title !== undefined) {
			component.queryById("omicNameFieldAlt").setValue(values.title);
		}
		if (values.configVars !== undefined) {
			component.queryById("configVarsFieldAlt").setValue(values.configVars);
		}
		if (values.enrichmentType !== undefined) {
			component.queryById("enrichmentTypeFieldAlt").setValue(values.enrichmentType);
		}
		this.toogleContent();
		return this;
	};

	/**
	* Display-only example mode for the MORE panel.
	*
	* MORE never had an example. Its inputs are also the least guessable in the
	* application -- a per-sample matrix with replicates rather than the log
	* ratios every other omic takes, plus a numeric 0/1 design matrix and one
	* association file per regulatory omic -- so "load an example and look at
	* the files" was the one thing a user could not do for the format that most
	* needed it.
	*
	* Only labels are set here; the server resolves the real files from the
	* manifest when the form posts to dm_fromMOREtoGenes/example/<id>. The model
	* settings (method, alpha, VIP, R2) come from the manifest too --
	* MOREServlet's example branch returns immediately after applyMoreScenario
	* and never reaches the "6. Model Parameters" block that reads the form -- so
	* lockFormForExample marks them read-only along with everything else. They
	* were left editable here on the belief that they were honoured; they are
	* not, and an editable field that changes nothing is the T1 defect in
	* miniature.
	*
	* @param {Object} scenario the entry from /example_datasets.
	*/
	this.setExampleMode = function(scenario) {
		var component = this.getComponent().queryById("itemsContainer");
		var omicNames = (scenario && scenario.omicNames) || ["Regulatory omic"];

		var label = function(itemId, text) {
			setExampleLabel(component.queryById(itemId), text);
		};

		label("conditionsFileSelector", "experimental design (samples × groups)");
		label("rnaseqauxFileSelector", "target gene expression (per sample)");
		label("mainFileSelector", omicNames[0] + " — regulator values");
		label("moreAssociationsFileSelector", omicNames[0] + " — associations");
		label("moreRelevantFileSelector", omicNames[0] + " — relevant regulators");

		// The omic name is `allowBlank: false`, so leaving it empty makes
		// checkForm() refuse to submit -- the example would load and then
		// silently fail to run. The server takes the name from the manifest
		// regardless; this is what lets the form validate.
		var nameField = component.queryById("omicNameField");
		if (nameField) {
			nameField.setValue(omicNames[0]);
			nameField.setDisabled(true);
		}

		// The manifest may carry more regulatory omics than the single block
		// the panel starts with. Rather than synthesising extra blocks -- which
		// would have to mirror the "+ Add another Regulatory Omic" handler and
		// drift from it -- say so, since the server loads all of them regardless.
		if (omicNames.length > 1) {
			this.getComponent().queryById("itemsContainer").add({
				xtype: 'box',
				html: '<p style="margin:6px 0 0 0;font-size:12px;color:#6B6B6B;">' +
					'This example also includes <b>' +
					Ext.String.htmlEncode(omicNames.slice(1).join(', ')) +
					'</b>. Every regulatory omic in the dataset is analysed; only ' +
					'the first is shown above.</p>'
			});
		}
		return this;
	};

	/*********************************************************************
	* COMPONENT DECLARATION
	***********************************************************************/
	this.initComponent = function() {
		var me = this;
		this.component = Ext.widget({
			xtype: "container",
			flex: 1,
			type: me.type,
			cls: "omicbox " + this.class,
			layout: {
				align: 'stretch',
				type: 'vbox'
			},
			items: [{
				xtype: "box",
				flex: 1,
				cls: "omicboxTitle moreBasedFileBox",
				html: '<h4><a class="deleteOmicBox" href="javascript:void(0)" style="margin: 0; float:right;  padding-right: 15px;">' +
				(me.removable ? ' <i class="fa fa-trash"></i></a>' : "</a>") + this.title +
				'</h4>'
			},
			{
				xtype: "container",
				itemId: "itemsContainer",
				layout: {
					align: 'stretch',
					type: 'vbox'
				},
				padding: 10,
				defaults: {
					labelAlign: "right",
					labelWidth: 150,
					maxLength: 100
				},
				items: [{
					xtype: 'textfield',
					name: "name_prefix",
					hidden: true,
					itemId: "namePrefix",
					value: this.namePrefix
				},
				{
					xtype: 'box',
					html: '<hr><h5>Experimental Design</h5>'
				},
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Conditions file',
					namePrefix: 'conditions',
					itemId: "conditionsFileSelector",
					helpTip: "Upload the Experimental Design / Conditions file mapping samples to conditions."
				},
				{
					xtype: 'box',
					html: '<hr><h5>Target Omic (Gene Expression)</h5>'
				},
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: "Gene expression dataset",
					namePrefix: 'rnaseqaux',
					itemId: "rnaseqauxFileSelector",
					helpTip: "Upload the target gene expression dataset used for regulatory analysis."
				},
				{
					xtype: 'textfield',
					fieldLabel: 'File Type',
					name: 'rnaseqaux_file_type',
					hidden: true,
					itemId: "rnaseqauxFileTypeSelector",
					value: "Gene Expression file"
				},
				{
					xtype: 'box',
					html: '<hr><h5>Regulatory Omic Data</h5>'
				},
				{
					xtype: 'combo',
					fieldLabel: 'Omic Name',
					name: 'omic_name_0',
					itemId: "omicNameField",
					displayField: 'name',
					valueField: 'name',
					emptyText: 'Type or choose the omic type',
					queryMode: 'local',
					editable: true,
					allowBlank: false,
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['name'],
						autoLoad: true,
						proxy: {
							type: 'ajax',
							url: 'resources/data/all_omics.json',
							reader: {
								type: 'json',
								root: 'omics',
								successProperty: 'success'
							}
						}
					})
				},
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Regulators expression file',
					namePrefix: 'file_0',
					itemId: "mainFileSelector",
					helpTip: "Upload the quantification file (i.e. miRNA Quantification) or choose it from your data folder. See above the accepted format for the file."
				},
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Relevant regulators file<br>(optional)',
					namePrefix: 'relevant_file_0',
					itemId: "moreRelevantFileSelector",
					helpTip: "Upload the list of relevant (differentially expressed) features (TAB format) or choose it from your data folder. See above the accepted format for the file."
				},
				{
					xtype: "myFilesSelectorButton",
					fieldLabel: 'Associations file',
					namePrefix: 'assoc_file_0',
					itemId: "moreAssociationsFileSelector",
					helpTip: "Upload the reference file that relates each feature (i.e. miRNA) with its potential targets. This information is usually extracted from popular databases such as miRbase for miRNAs. See above the accepted format for the file."
				},
				{
					// Per-omic low-variation filter (MORE `minVariation`). Each
					// regulatory omic carries its own threshold so heterogeneous
					// data types (e.g. methylation vs. miRNA) can be filtered
					// independently. Default 0 = keep all but constant regulators.
					xtype: 'numberfield',
					name: 'more_minvar_0',
					fieldLabel: 'Min. variation',
					value: 0,
					minValue: 0,
					step: 0.01,
					allowDecimals: true,
					allowBlank: false,
					helpTip: "Minimum change in standard deviation (numeric regulators) or proportion (binary) a regulator must show across conditions to avoid being filtered as low-variation. Applied to this regulatory omic only. 0 = keep all but constant regulators."
				},
				{
					xtype: 'container',
					itemId: 'addOmicWrapper',
					layout: { type: 'hbox', pack: 'center' },
					margin: '5 0 15 0',
					items: [{
						xtype: 'button',
						text: '<i class="fa fa-plus-circle"></i> Add another Regulatory Omic',
						width: 250,
						handler: function(btn) {
							var container = btn.up('#itemsContainer');
							if (!container.moreOmicCount) container.moreOmicCount = 0;
							container.moreOmicCount++;
							var i = container.moreOmicCount;
							var insertIdx = container.items.indexOf(btn.up('#addOmicWrapper'));
						
						container.insert(insertIdx, [
							{
								xtype: 'box',
								html: '<hr><h5>Regulatory Omic Data ' + (i+1) + '</h5>'
							},
							{
								xtype: 'combo',
								fieldLabel: 'Omic Name',
								name: 'omic_name_' + i,
								displayField: 'name',
								valueField: 'name',
								emptyText: 'Type or choose the omic type',
								queryMode: 'local',
								editable: true,
								allowBlank: false,
								store: Ext.create('Ext.data.ArrayStore', {
									fields: ['name'],
									autoLoad: true,
									proxy: {
										type: 'ajax',
										url: 'resources/data/all_omics.json',
										reader: {
											type: 'json',
											root: 'omics',
											successProperty: 'success'
										}
									}
								})
							},
							{
								xtype: "myFilesSelectorButton",
								fieldLabel: 'Regulators expression file',
								namePrefix: 'file_' + i,
								helpTip: "Upload the quantification file (i.e. miRNA Quantification) or choose it from your data folder. See above the accepted format for the file."
							},
							{
								xtype: "myFilesSelectorButton",
								fieldLabel: 'Relevant regulators file<br>(optional)',
								namePrefix: 'relevant_file_' + i,
								helpTip: "Upload the list of relevant (differentially expressed) features (TAB format) or choose it from your data folder. See above the accepted format for the file."
							},
							{
								xtype: "myFilesSelectorButton",
								fieldLabel: 'Associations file',
								namePrefix: 'assoc_file_' + i,
								helpTip: "Upload the reference file that relates each feature (i.e. miRNA) with its potential targets. This information is usually extracted from popular databases such as miRbase for miRNAs. See above the accepted format for the file."
							},
							{
								// Per-omic low-variation filter (MORE `minVariation`).
								// Mirrors the field on the first regulatory omic above.
								xtype: 'numberfield',
								name: 'more_minvar_' + i,
								fieldLabel: 'Min. variation',
								value: 0,
								minValue: 0,
								step: 0.01,
								allowDecimals: true,
								allowBlank: false,
								helpTip: "Minimum change in standard deviation (numeric regulators) or proportion (binary) a regulator must show across conditions to avoid being filtered as low-variation. Applied to this regulatory omic only. 0 = keep all but constant regulators."
							}
						]);
						setTimeout(function() { initializeTooltips(".helpTip"); }, 100);
						}
					}]
				},
				{
					xtype: 'box',
					html: '<hr><h5>MORE Algorithm Parameters</h5>'
				},
				{
					xtype: 'combo',
					itemId: "moreMethodField",
					name: 'more_method',
					fieldLabel: 'Regression Method',
					editable: false,
					allowBlank: false,
					value: "PLS1",
					displayField: 'label',
					valueField: 'value',
					store: Ext.create('Ext.data.ArrayStore', {
						fields: ['label', 'value'],
						data: [
							["PLS1 (Partial Least Squares)", "PLS1"],
							["MLR (Multiple Linear Regression)", "MLR"]
						]
					}),
					helpTip: "Select the regression model to use for finding significant regulators.",
					listeners: {
						change: function(combo, newValue) {
							var container = combo.up('#itemsContainer');
							var isPLS1 = newValue === 'PLS1';
							var alphaField = container.queryById('moreAlphaField');
							var vipField = container.queryById('moreVipField');
							// Disable as well as hide. Both fields are allowBlank:false,
							// and a merely hidden ExtJS field is still validated and still
							// submitted -- so clearing Alpha and then switching to MLR left
							// the form permanently invalid with "Invalid Form. Please check
							// the form errors." and no visible field to correct.
							// Disabling excludes them from validation and from the POST;
							// MORE's GetMLR takes neither alfa nor vip, so MLR loses
							// nothing, and MOREServlet defaults them when absent.
							[alphaField, vipField].forEach(function(field) {
								if (!field) { return; }
								field.setVisible(isPLS1);
								field.setDisabled(!isPLS1);
							});
						}
					}
				},
				{
					xtype: 'numberfield',
					itemId: "moreAlphaField",
					name: 'more_alpha',
					fieldLabel: 'Alpha (Significance)',
					value: 0.05,
					minValue: 0.0001,
					maxValue: 1,
					step: 0.01,
					allowDecimals: true,
					allowBlank: false,
					helpTip: "Significance threshold (alpha)."
				},
				{
					xtype: 'numberfield',
					itemId: "moreVipField",
					name: 'more_vip',
					fieldLabel: 'VIP threshold',
					value: 0.8,
					minValue: 0,
					maxValue: 10,
					step: 0.1,
					allowDecimals: true,
					allowBlank: false,
					helpTip: "VIP threshold for PLS1 model."
				},
				{
					xtype: 'numberfield',
					itemId: "moreR2Field",
					name: 'more_filter_r2',
					fieldLabel: 'R2 Filter',
					value: 0.0,
					minValue: 0,
					maxValue: 1,
					step: 0.1,
					allowDecimals: true,
					allowBlank: false,
					helpTip: "R2 filter threshold."
				}]
			},
			{
				xtype: "container",
				itemId: "itemsContainerAlt",
				hidden: true,
				disabled: true,
				layout: {
					align: 'stretch',
					type: 'vbox'
				},
				padding: 10,
				defaults: {
					labelAlign: "right",
					labelWidth: 150,
					maxLength: 100
				},
				items: [{
					xtype: 'filefield',
					name: this.namePrefix + '_file_0',
					hidden: true
				}, {
					xtype: 'textfield',
					name: this.namePrefix + '_origin_0',
					value: 'mydata',
					hidden: true
				}, {
					xtype: 'textfield',
					name: this.namePrefix + '_file_type_0',
					value: 'Gene Expression file',
					hidden: true
				}, {
					xtype: 'filefield',
					name: this.namePrefix + '_relevant_file_0',
					hidden: true
				}, {
					xtype: 'textfield',
					name: this.namePrefix + '_relevant_0_origin',
					value: 'mydata',
					hidden: true
				}, {
					xtype: 'textfield',
					name: this.namePrefix + '_relevant_file_type_0',
					value: 'Relevant gene list',
					hidden: true
				}, {
					xtype: 'filefield',
					name: this.namePrefix + '_associations_file_0',
					hidden: true
				}, {
					xtype: 'textfield',
					name: this.namePrefix + '_associations_0_origin',
					value: 'mydata',
					hidden: true
				}, {
					xtype: 'textfield',
					name: this.namePrefix + '_associations_file_type_0',
					value: 'Associations file',
					hidden: true
				}, {
					xtype: 'filefield',
					name: this.namePrefix + '_relevant_associations_file_0',
					hidden: true
				}, {
					xtype: 'textfield',
					name: this.namePrefix + '_relevant_associations_0_origin',
					value: 'mydata',
					hidden: true
				}, {
					xtype: 'textfield',
					name: this.namePrefix + '_relevant_associations_file_type_0',
					value: 'Relevant associations file',
					hidden: true
				}, {
					xtype: 'textfield',
					fieldLabel: 'Omic Name',
					name: this.namePrefix + '_omic_name_0',
					hidden: true,
					itemId: "omicNameFieldAlt",
					value: this.omicName
				}, {
					xtype: 'textfield',
					fieldLabel: 'Output File',
					name: this.namePrefix + '_filelocation_0',
					hidden: true,
					itemId: "mainFileFieldAlt"
				}, {
					xtype: 'textfield',
					fieldLabel: 'Relevant Regulators File',
					name: this.namePrefix + '_relevant_filelocation_0',
					hidden: true,
					itemId: "secondaryFileFieldAlt"
				}, {
					xtype: 'textfield',
					fieldLabel: 'Associations File',
					name: this.namePrefix + '_associations_filelocation_0',
					hidden: true,
					itemId: "thirdFileFieldAlt"
				}, {
					xtype: 'textfield',
					fieldLabel: 'Relevant Associations File',
					name: this.namePrefix + '_relevant_associations_filelocation_0',
					hidden: true,
					itemId: "fourthFileFieldAlt"
				}, {
					xtype: 'textfield',
					fieldLabel: 'Config Vars',
					name: this.namePrefix + '_config_args_0',
					hidden: true,
					itemId: "configVarsFieldAlt"
				}, {
					xtype: 'textfield',
					fieldLabel: 'Enrichment type',
					name: this.namePrefix + '_enrichment_0',
					hidden: true,
					itemId: "enrichmentTypeFieldAlt",
					value: "genes"
				}, {
					xtype: 'textfield',
					hidden: true,
					fieldLabel: 'Map to',
					name: this.namePrefix + '_match_type_0',
					itemId: "matchTypeSelectorAlt",
					value: 'gene'
				}, {
					xtype: 'box',
					html: '<h5 style="color: #689F38;"><i class="fa fa-check"></i> Files processed correctly!</h5>'
				}]
			}],
			setContent: function(target, values) {
				var component = this.queryById(target);
				if (values.mainFile !== undefined) {
					component.queryById("mainFileFieldAlt").setValue(values.mainFile);
				}
				if (values.secondaryFile !== undefined) {
					component.queryById("secondaryFileFieldAlt").setValue(values.secondaryFile);
				}
				if (values.thirdFile !== undefined) {
					component.queryById("thirdFileFieldAlt").setValue(values.thirdFile);
				}
				if (values.fourthFile !== undefined && values.fourthFile !== null) {
					component.queryById("fourthFileFieldAlt").setValue(values.fourthFile);
				}
				if (values.title !== undefined) {
					component.queryById("omicNameFieldAlt").setValue(values.title);
				}
				if (values.configVars !== undefined) {
					component.queryById("configVarsFieldAlt").setValue(values.configVars);
				}
				if (values.enrichmentType !== undefined) {
					component.queryById("enrichmentTypeFieldAlt").setValue(values.enrichmentType);
				}

				// Multi-omic propagation. `setContent` is a method of the inner Ext
				// widget, so `this` here is the component, NOT the MORESubmittingPanel
				// — `this.namePrefix` would resolve to undefined and the alt fields
				// would be named "undefined_file_1" etc. Use the closure-captured
				// `me` (the panel) so the per-omic fields share the panel's prefix
				// and saveFiles can pair each omic 1+ with its omic_name/filelocation.
				if (values.response && values.response.omicsCount > 1) {
					for (var i = 1; i < values.response.omicsCount; i++) {
						component.add([
							{ xtype: 'filefield', name: me.namePrefix + '_file_' + i, hidden: true },
							{ xtype: 'textfield', name: me.namePrefix + '_origin_' + i, value: 'mydata', hidden: true },
							{ xtype: 'textfield', name: me.namePrefix + '_file_type_' + i, value: 'Gene Expression file', hidden: true },
							{ xtype: 'filefield', name: me.namePrefix + '_relevant_file_' + i, hidden: true },
							{ xtype: 'textfield', name: me.namePrefix + '_relevant_' + i + '_origin', value: 'mydata', hidden: true },
							{ xtype: 'textfield', name: me.namePrefix + '_relevant_file_type_' + i, value: 'Relevant gene list', hidden: true },
							{ xtype: 'filefield', name: me.namePrefix + '_associations_file_' + i, hidden: true },
							{ xtype: 'textfield', name: me.namePrefix + '_associations_' + i + '_origin', value: 'mydata', hidden: true },
							{ xtype: 'textfield', name: me.namePrefix + '_associations_file_type_' + i, value: 'Associations file', hidden: true },
							{ xtype: 'filefield', name: me.namePrefix + '_relevant_associations_file_' + i, hidden: true },
							{ xtype: 'textfield', name: me.namePrefix + '_relevant_associations_' + i + '_origin', value: 'mydata', hidden: true },
							{ xtype: 'textfield', name: me.namePrefix + '_relevant_associations_file_type_' + i, value: 'Relevant associations file', hidden: true },
							{ xtype: 'textfield', name: me.namePrefix + '_omic_name_' + i, hidden: true, value: values.response['omicName_' + i] },
							{ xtype: 'textfield', name: me.namePrefix + '_filelocation_' + i, hidden: true, value: values.response['mainOutputFileName_' + i] },
							{ xtype: 'textfield', name: me.namePrefix + '_relevant_filelocation_' + i, hidden: true, value: values.response['secondOutputFileName_' + i] },
							{ xtype: 'textfield', name: me.namePrefix + '_associations_filelocation_' + i, hidden: true, value: values.response['thirdOutputFileName_' + i] },
							{ xtype: 'textfield', name: me.namePrefix + '_relevant_associations_filelocation_' + i, hidden: true, value: values.response['fourthOutputFileName_' + i] },
							{ xtype: 'textfield', name: me.namePrefix + '_config_args_' + i, hidden: true, value: values.configVars },
							{ xtype: 'textfield', name: me.namePrefix + '_enrichment_' + i, hidden: true, value: values.enrichmentType },
							{ xtype: 'textfield', name: me.namePrefix + '_match_type_' + i, hidden: true, value: 'gene' }
						]);
					}

					// Surface the multi-omic outcome to the user. Without this they
					// only see "Files processed correctly!" and have no way to know
					// whether the second omic actually came through to PA Step 1.
					var processedNames = [values.title || values.response['omicName_0']];
					for (var k = 1; k < values.response.omicsCount; k++) {
						processedNames.push(values.response['omicName_' + k]);
					}
					component.add({
						xtype: 'box',
						html: '<p style="margin: 5px 155px; font-size: 12px; color: #689F38;">' +
						      '<i class="fa fa-check-circle"></i> ' + values.response.omicsCount +
						      ' regulatory omics processed: <b>' + processedNames.join(', ') + '</b></p>'
					});
				}

				var isVisible = component.isVisible();
				component.setVisible(!isVisible);
				component.setDisabled(isVisible);
		
				var mainContainer = this.queryById("itemsContainer");
				if (mainContainer) {
					mainContainer.setVisible(isVisible);
					mainContainer.setDisabled(!isVisible);
				}
				return this;
			},
			isValid: function() {
				var valid = true;
				var component = this.queryById("itemsContainerAlt");
				if (!component || !component.isVisible()) {
					component = this.queryById("itemsContainer");
				}
				if (!component) return false;
				var items = component.query("field");
				for (var i in items) {
					valid = valid && (this.items[i] || items[i].validate());
				}
		
				if (component.queryById("conditionsFileSelector") && component.queryById("conditionsFileSelector").getValue() === "") {
					valid = false;
					component.queryById("conditionsFileSelector").markInvalid("Please, provide the conditions file.");
				}
				if (component.queryById("mainFileSelector") && component.queryById("mainFileSelector").getValue() === "") {
					valid = false;
					component.queryById("mainFileSelector").markInvalid("Please, provide a regulatory data file.");
				}
				if (component.queryById("rnaseqauxFileSelector") && component.queryById("rnaseqauxFileSelector").getValue() === "") {
					valid = false;
					component.queryById("rnaseqauxFileSelector").markInvalid("Please, provide the gene expression dataset.");
				}
				
				return valid;
			},
			isEmpty: function() {
				var component = this.queryById("itemsContainerAlt");
				if (component && component.isVisible()) {
					return false; // Already processed and has results
				}
				component = this.queryById("itemsContainer");
				if (component && component.queryById("mainFileSelector") && component.queryById("mainFileSelector").getValue() !== "") {
					return false;
				}
				return true;
			},
			listeners: {
				boxready: function() {
					initializeTooltips(".helpTip");
					$(this.getEl().dom).find("a.deleteOmicBox").click(function() {
						me.removeOmicSubmittingPanel();
					});
				}
			}
		});

		return this.component;
	};

	return this;
}
MORESubmittingPanel.prototype = new DefaultSubmittingPanel;


window.cookieconsent.initialise({
	container: document.getElementById("content"),
	palette: {
		popup: {background: "#f6f6f6"},
		button: {background: "#2684ff"},
	},
	revokable: true,
	onStatusChange: function (status) {
		console.log(this.hasConsented() ?
			'enable cookies' : 'disable cookies');
	},
	law: {
		regionalLaw: false,
	},
	location: true,
	content: {
		header: 'Cookies used on the website!',
		message: 'This website uses cookies to improve your experience.',
		dismiss: 'Got it!',
		allow: 'Allow cookies',
		deny: 'Decline',
		link: 'Learn more',
		href: 'https://paintomics.uv.es/conditions.html',
		close: '&#x274c;',
		policy: 'Cookie Policy',
		target: '_blank',
	},
	position:"bottom-left",
	elements: {
		link: '<a aria-label="learn more about cookies" tabindex="0" class="cc-link" href="" target="_blank"></a>'
	}
});

/*********************************************************************
 * AI PROVENANCE                                    ******************
 *********************************************************************
 * Names the recipient of the data in the consent surfaces.
 *
 * The provider, its host and the model are all chosen server-side by
 * AI_LLM_PROVIDER and are all env-overridable, so the browser cannot know any
 * of them. It used to not try: the consent label said "external AI service"
 * and the notice said "external LLM servers", which is the same amount of
 * information as saying nothing. The only string in the whole product that
 * named the gateway was the missing-API-key error, so a working install told
 * the user nothing about where their data went and a broken one told them
 * everything.
 *
 * /ai_provider answers it. One request, cached for the page, and every
 * placeholder that happens to be in the DOM is filled from the same answer.
 * If the request fails the placeholders keep the wording they shipped with,
 * which is vaguer but still true -- a consent notice must not degrade into a
 * claim the server has not confirmed.
 *********************************************************************/
var AI_PROVIDER_INFO = null;
var _aiProviderRequest = null;

/* Runs `callback(info)` once the provider description is known, immediately if
   it already is. Never calls back on failure: the fallback copy is what the
   markup already contains. */
function withAIProviderInfo(callback) {
	if (AI_PROVIDER_INFO !== null) {
		callback(AI_PROVIDER_INFO);
		return;
	}
	if (_aiProviderRequest === null) {
		_aiProviderRequest = $.ajax({
			type: "GET", url: SERVER_URL_AI_PROVIDER, dataType: "json"
		});
	}
	_aiProviderRequest.done(function (response) {
		if (!response || response.success !== true || !response.host) {
			return;
		}
		AI_PROVIDER_INFO = response;
		callback(response);
	});
}

/* Fills whichever provenance placeholders exist under `root` (the document by
   default). Called twice with different roots: once when step 1 renders, for
   the consent label and the callout, and again when the privacy notice is
   built, because that modal does not exist until the icon is clicked. */
function fillAIProvenance(root) {
	root = root || document;

	withAIProviderInfo(function (info) {
		/* getAIProviderInfo answers for a host it has no entry for by setting
		   `operator` and `summary` to the bare hostname (AIInterpretServlet.py
		   :112-113). That is the right thing for it to do - the hostname is
		   still true - but the sentences below were written as though the two
		   were always distinct, so an unrecognised gateway printed its own name
		   twice: "llm.example.org (llm.example.org)" in the consent label and
		   "send the data to llm.example.org - llm.example.org" in the notice.
		   Reads as a bug in a paragraph whose whole job is to be trusted. */
		var operatorIsHost = !info.operator || info.operator === info.host;
		var summaryIsHost = !info.summary || info.summary === info.host;

		/* The model identifier is deliberately not shown anywhere in the
		   interface. /ai_provider still reports it -- it is a true fact about
		   the configuration and other callers may want it -- but naming a
		   specific build in consent copy invites the reader to evaluate the
		   model rather than the decision in front of them, and the string goes
		   stale the moment the gateway is repointed. Who operates the endpoint
		   and where it runs is what a consent decision actually turns on. */

		var name = root.querySelector("#aiProviderName");
		if (name) {
			/* Deliberately the operator and the host rather than a phrase like
			   "a CSIC gateway": the host is the checkable fact, and this label
			   is the one piece of consent copy every user reads. */
			name.textContent = operatorIsHost
				? info.host
				: info.operator + " (" + info.host + ")";
		}

		var inline = root.querySelector("#aiProviderInline");
		if (inline) {
			inline.textContent = " This server sends the data to " + info.summary + ".";
		}

		var where = root.querySelector("#aiGdprWhere");
		if (where) {
			where.innerHTML = "<strong>Where it runs:</strong> this server is configured to send "
				+ "the data to <strong>" + Ext.String.htmlEncode(info.host) + "</strong>"
				+ (summaryIsHost ? "" : " &mdash; " + Ext.String.htmlEncode(info.summary))
				+ ".";
		}

		var transfer = root.querySelector("#aiGdprTransfer");
		if (transfer) {
			/* The page used to assert GDPR Chapter V unconditionally -- Articles
			   44-49, "non-EU processors", Standard Contractual Clauses -- which
			   does not describe the default configuration at all, and reads as
			   boilerplate nobody updated. Stated from the configuration
			   instead, and left blank where the server cannot say, because a
			   guess about which legal regime applies is worse than silence. */
			if (info.inEU === true) {
				transfer.innerHTML = "<strong>Transfers:</strong> this deployment sends the data to "
					+ "an endpoint operated within the EU, so Chapter V of the GDPR "
					+ "(Articles 44&ndash;49, transfers to third countries) does not apply to it.";
			} else if (info.inEU === false) {
				transfer.innerHTML = "<strong>Transfers:</strong> this deployment sends the data "
					+ "outside the EU. Under GDPR Articles 44&ndash;49, transferring identifiable "
					+ "personal data to a non-EU processor requires appropriate safeguards, such as "
					+ "Standard Contractual Clauses.";
			}
		}
	});
}
