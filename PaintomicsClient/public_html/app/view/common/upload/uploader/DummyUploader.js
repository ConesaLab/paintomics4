Ext.define('Ext.upload.uploader.DummyUploader', {
    extend : 'Ext.upload.uploader.AbstractUploader',

    delay : 1000,

    uploadItem : function(item) {
        item.setUploading();

        var task = new Ext.util.DelayedTask(function() {
            this.fireEvent('uploadsuccess', item, {
                success : true,
                message : 'OK',
                response : null
            });
        }, this);

        task.delay(this.delay);
    },

    abortUpload : function() {
    }
});