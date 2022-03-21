/**
 * The main upload dialog.
 * 
 * Mostly, this may be the only object you need to interact with. Just initialize it and show it:
 * 
 *     @example
 *     var dialog = Ext.create('Ext.upload.Dialog', {
 *         dialogTitle: 'My Upload Widget',
 *         uploadUrl: 'upload.php'
 *     }); 
 *     dialog.show();
 * 
 */
Ext.define('Ext.upload.Dialog', {
    extend : 'Ext.window.Window',

    /**
     * @cfg {Number} [width=700]
     */
    width : 700,

    /**
     * @cfg {Number} [height=500]
     */
    height : 500,

    border : 0,

    config : {
        /**
         * @cfg {String}
         * 
         * The title of the dialog.
         */
        dialogTitle : '',

        /**
         * @cfg {boolean} [synchronous=false]
         * 
         * If true, all files are uploaded in a sequence, otherwise files are uploaded simultaneously (asynchronously).
         */
        synchronous : true,

        /**
         * @cfg {String} uploadUrl (required)
         * 
         * The URL to upload files to.
         */
        uploadUrl : '',

        /**
         * @cfg {Object}
         * 
         * Params passed to the uploader object and sent along with the request. It depends on the implementation of the
         * uploader object, for example if the {@link Ext.upload.uploader.ExtJsUploader} is used, the params are sent
         * as GET params.
         */
        uploadParams : {},

        /**
         * @cfg {Object}
         * 
         * Extra HTTP headers to be added to the HTTP request uploading the file.
         */
        uploadExtraHeaders : {},

        /**
         * @cfg {Number} [uploadTimeout=6000]
         * 
         * The time after the upload request times out - in miliseconds.
         */
        uploadTimeout : 60000,

        // strings
        textClose : 'Close'
    },

    /**
     * Constructor.
     */
    constructor : function(config) {
        this.initConfig(config);
        return this.callParent(arguments);
    },

    /**
     * @private
     */
    initComponent : function() {

        this.addEvents({
            /**
             * @event
             * 
             * Fired when all files has been processed.
             * 
             * @param {Ext.upload.Dialog} dialog
             * @param {Ext.upload.Manager} manager
             * @param {Ext.upload.Item[]} items
             * @param {Number} errorCount
             */
            'uploadcomplete' : true
        });

        if (!Ext.isObject(this.panel)) {
            this.panel = Ext.create('Ext.upload.Panel', {
                synchronous : this.synchronous,
                uploadUrl : this.uploadUrl,
                uploadParams : this.uploadParams,
                uploadExtraHeaders : this.uploadExtraHeaders,
                uploadTimeout : this.uploadTimeout
            });
        }

        this.relayEvents(this.panel, [
                'uploadcomplete'
            ]);

        Ext.apply(this, {
            title : this.dialogTitle,
            layout : 'fit',
            items : [
                this.panel
            ],
            dockedItems : [
                {
                    xtype : 'toolbar',
                    dock : 'bottom',
                    ui : 'footer',
                    defaults : {
                        minWidth : this.minButtonWidth
                    },
                    items : [
                        '->',
                        {
                            text : this.textClose,
                            cls : 'x-btn-text-icon',
                            scope : this,
                            handler : function() {
                                this.close();
                            }
                        }
                    ]
                }
            ]
        });

        this.callParent(arguments);
    }

});