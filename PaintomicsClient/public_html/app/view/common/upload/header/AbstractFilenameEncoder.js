/**
 * Abstract filename encoder.
 */
Ext.define('Ext.upload.header.AbstractFilenameEncoder', {

    config : {},

    type : 'generic',

    contructor : function(config) {
        this.initConfig(config);
    },

    encode : function(filename) {},

    getType : function() {
        return this.type;
    }
});
