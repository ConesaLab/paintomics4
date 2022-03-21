//mongo PaintomicsDB "cleanDatabase.js" | tee cleanDatabase3.log

Date.prototype.stringFormat = function() {
  var mm = this.getMonth() + 1; // getMonth() is zero-based
  var dd = this.getDate();

  return [this.getFullYear(),
          (mm>9 ? '' : '0') + mm,
          (dd>9 ? '' : '0') + dd,
          this.getHours(),
          this.getMinutes()
         ].join('');
};

var userCursor = db.userCollection.find();
var maxDateGuest = new Date(new ISODate() - (7 * 24 * 60 * 60 * 1000)).stringFormat();
var maxDateReg = new Date(new ISODate() - (90 * 24 * 60 * 60 * 1000)).stringFormat();

print('Max date for guest is ' + maxDateGuest);
print('Max date for registered is ' + maxDateReg);

while (userCursor.hasNext()) {
	var user = userCursor.next();
	print("Cleaning data user for " + user.userName + " (userId: " +  user.userID + ")");
	var maxDate = ((user.is_guest)?maxDateGuest:maxDateReg);
	var jobCursor = db.jobInstanceCollection.find({userID: "" + user.userID, date : {$lt: maxDate}});
	while (jobCursor.hasNext()) {
		var job = jobCursor.next();
		print("    -- Cleaning job " +  job.jobID);
		db.featuresCollection.remove({jobID: job.jobID});
		print("        [OK] All features deleted");
		db.pathwaysCollection.remove({jobID: job.jobID});
		print("        [OK] All pathways deleted");
		db.visualOptionsCollection.remove({jobID: job.jobID});
		print("        [OK] All visualOptions deleted");
		db.jobInstanceCollection.remove({jobID: job.jobID});
		print("        [OK] Removed job instance");
	}
}

//Reindex the collections every N days
//db.userCollection.reIndex();
//db.jobInstanceCollection.reIndex();
//db.featuresCollection.reIndex();
//db.pathwaysCollection.reIndex();
//db.visualOptionsCollection.reIndex();
//db.fileCollection.reIndex();
